import unittest
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from m3u8_bridge.gateway import HLSGateway


class GatewayRewriteTests(unittest.TestCase):
    def test_fetch_uses_a_real_bounded_curl_process(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = b'gateway-test'
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                return

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            gateway = HLSGateway()
            gateway.register('job', f'http://127.0.0.1:{server.server_address[1]}/segment.ts', {}, '')
            payload, _content_type, status, _headers = gateway._fetch(
                f'http://127.0.0.1:{server.server_address[1]}/segment.ts', gateway.streams['job'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(payload, b'gateway-test')
        self.assertEqual(status, 200)

    def test_fetch_retries_one_429_then_succeeds(self):
        requests = {'count': 0}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests['count'] += 1
                if requests['count'] == 1:
                    self.send_response(429)
                    self.send_header('Retry-After', '0')
                    self.end_headers()
                    return
                payload = b'recovered'
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                return

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            gateway = HLSGateway()
            url = f'http://127.0.0.1:{server.server_address[1]}/segment.ts'
            gateway.register('job', url, {}, '')
            payload, _content_type, status, _headers = gateway._fetch(url, gateway.streams['job'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(requests['count'], 2)
        self.assertEqual(payload, b'recovered')
        self.assertEqual(status, 200)

    def test_rewrites_relative_segments_and_uri_attributes(self):
        gateway = HLSGateway('http://127.0.0.1:8765')
        gateway.register('job', 'https://media.example/master.m3u8', {'Referer': 'https://media.example/page'}, 'http://127.0.0.1:7890')
        context = gateway.streams['job']
        rewritten = gateway._rewrite(
            '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin"\n#EXTINF:2,\nsegments/0001.ts\n',
            context.url,
            context,
        )
        self.assertIn('/hls/job/resource/', rewritten)
        self.assertIn('.ts', rewritten)
        self.assertEqual(context.resources, {
            next(key for key in context.resources if context.resources[key].endswith('/keys/key.bin')): 'https://media.example/keys/key.bin',
            next(key for key in context.resources if context.resources[key].endswith('/segments/0001.ts')): 'https://media.example/segments/0001.ts',
        })

    def test_repairs_observed_googleusercontent_download_path(self):
        original = 'https://lh3.googleusercontent.com/d/abc123=d'
        repaired = HLSGateway._repair_googleusercontent(original)
        self.assertEqual(repaired, 'https://drive.usercontent.google.com/download?id=abc123&export=download&confirm=t')

    def test_fetch_bounds_upstream_waits_for_proxy_failures(self):
        gateway = HLSGateway()
        gateway.register('job', 'https://media.example/master.m3u8', {}, 'http://127.0.0.1:7890')
        observed = {}

        class FakeProcess:
            returncode = 0

            def communicate(self, timeout=None):
                return b'ok\n__MB_STATUS__200', b''

            def poll(self):
                return self.returncode

        def fake_popen(args, **kwargs):
            observed['args'] = args
            observed.update(kwargs)
            return FakeProcess()

        with patch('m3u8_bridge.gateway.subprocess.Popen', side_effect=fake_popen):
            payload, _content_type, status, _headers = gateway._fetch(
                'https://media.example/segment.ts', gateway.streams['job'])

        self.assertEqual(payload, b'ok')
        self.assertEqual(status, 200)
        self.assertIn('--connect-timeout', observed['args'])
        self.assertIn('--retry-max-time', observed['args'])
        self.assertIn('--retry-all-errors', observed['args'])
        self.assertEqual(observed['args'][observed['args'].index('--retry') + 1], '1')
        self.assertEqual(observed['args'][observed['args'].index('--max-time') + 1], '30')
        self.assertTrue(observed['start_new_session'])

    def test_fetch_terminates_an_inflight_process_when_cancelled(self):
        gateway = HLSGateway()
        cancel_event = __import__('threading').Event()
        gateway.register('job', 'https://media.example/master.m3u8', {}, '', cancel_event)
        process_state = {'terminated': False}

        class HangingProcess:
            returncode = None
            pid = 12345

            def communicate(self, timeout=None):
                cancel_event.set()
                raise __import__('subprocess').TimeoutExpired('curl', timeout)

            def poll(self):
                return None if not process_state['terminated'] else 143

            def wait(self, timeout=None):
                process_state['terminated'] = True
                self.returncode = 143

        with patch('m3u8_bridge.gateway.subprocess.Popen', return_value=HangingProcess()), patch('m3u8_bridge.gateway.os.killpg'):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                gateway._fetch('https://media.example/segment.ts', gateway.streams['job'])
        self.assertTrue(process_state['terminated'])

    def test_terminate_reaps_process_after_forced_kill(self):
        state = {'wait_calls': 0, 'killed': False}

        class StubbornProcess:
            pid = 12345

            def poll(self):
                return None

            def wait(self, timeout=None):
                state['wait_calls'] += 1
                if not state['killed']:
                    raise __import__('subprocess').TimeoutExpired('curl', timeout)
                return -9

        def killpg(_pid, signal_number):
            if signal_number == __import__('signal').SIGKILL:
                state['killed'] = True

        with patch('m3u8_bridge.gateway.os.killpg', side_effect=killpg):
            HLSGateway._terminate(StubbornProcess())

        self.assertTrue(state['killed'])
        self.assertEqual(state['wait_calls'], 2)


if __name__ == '__main__':
    unittest.main()
