import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from m3u8_bridge.gateway import HLSGateway
from m3u8_bridge.server import Engine, Handler


class NetworkRoutingTests(unittest.TestCase):
    def test_real_hls_download_uses_proxy_only_for_upstream_and_produces_video(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg and ffprobe required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=5',
                            '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-f', 'hls', '-hls_time', '1',
                            str(source / 'playlist.m3u8')], check=True)
            proxied = []
            engine = Engine(database_path=root / 'history.sqlite3')

            class Proxy(BaseHTTPRequestHandler):
                def do_GET(self):
                    proxied.append(self.path)
                    if urlsplit(self.path).hostname != 'media.example.test':
                        self.send_error(502, 'Loopback must not use proxy')
                        return
                    payload = (source / Path(urlsplit(self.path).path).name).read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

                def log_message(self, *_args):
                    pass

            class Relay(BaseHTTPRequestHandler):
                def do_GET(self):
                    body, content_type, status, headers = engine.gateway.handle(self.path, self.headers.get('Range'))
                    self.send_response(status)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Content-Length', str(len(body)))
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *_args):
                    pass

            servers = [ThreadingHTTPServer(('127.0.0.1', 0), cls) for cls in (Proxy, Relay)]
            for server in servers:
                threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                proxy = f'http://127.0.0.1:{servers[0].server_port}'
                engine.gateway.base_url = f'http://127.0.0.1:{servers[1].server_port}'
                job = engine._new_job({'url': 'http://media.example.test/playlist.m3u8'}, 'hls', 'clip', 1, '')
                with patch.dict(os.environ, {'HTTP_PROXY': proxy, 'http_proxy': proxy, 'NO_PROXY': '*', 'no_proxy': '*'}):
                    engine._run_job(job, {'outputDir': str(root / 'output'), 'proxy': proxy}, {**engine.settings, 'ffmpegPath': ffmpeg})
                self.assertEqual(job['status'], 'completed', job['error'])
                streams = Engine._probe_streams(Path(job['outputPath']))
                self.assertEqual({stream['codec_type'] for stream in streams}, {'video', 'audio'})
                self.assertTrue(proxied)
                self.assertTrue(all(urlsplit(url).hostname == 'media.example.test' for url in proxied))
            finally:
                for server in servers:
                    server.shutdown()
                    server.server_close()
                engine._watchdog_stop.set()

    def test_hls_downloader_bypasses_proxy_but_gateway_keeps_it(self):
        for proxy in ('http://127.0.0.1:7890', 'socks5h://127.0.0.1:7890'):
            with self.subTest(proxy=proxy), tempfile.TemporaryDirectory() as directory:
                engine = Engine(database_path=Path(directory) / 'history.sqlite3')
                job = engine._new_job({'url': 'https://media.example.test/playlist.m3u8'}, 'hls', 'clip', 1, '')
                options = {}

                def constructor(value):
                    options.update(value)
                    return downloader.return_value

                def extract(url, download):
                    self.assertEqual(url, f'http://127.0.0.1:8765/hls/{job["id"]}/playlist.m3u8')
                    self.assertEqual(engine.gateway.streams[job['id']].proxy, proxy)
                    raise RuntimeError('fixture stops before download')

                with patch('yt_dlp.YoutubeDL') as downloader, patch.object(engine.gateway, 'detect_png_segments', return_value=None):
                    downloader.side_effect = constructor
                    downloader.return_value.__enter__.return_value.extract_info.side_effect = extract
                    engine._run_job(job, {'outputDir': directory, 'proxy': proxy}, {**engine.settings, 'ffmpegPath': 'ffmpeg'})
                self.assertEqual(options.get('proxy'), '')
                self.assertEqual(job['error'], 'fixture stops before download')
                engine._watchdog_stop.set()

    def test_empty_proxy_explicitly_disables_environment_proxy_for_direct_downloads(self):
        options = Engine._yt_dlp_options(Path('/tmp'), 'clip', 'ffmpeg', {}, '', lambda _: None)
        self.assertIn('proxy', options)
        self.assertEqual(options['proxy'], '')

    def test_gateway_obeys_explicit_proxy_despite_no_proxy_environment(self):
        gateway = HLSGateway()
        gateway.register('job', 'https://media.example.test/playlist.m3u8', {}, 'socks5h://127.0.0.1:7890')
        with patch.dict(os.environ, {'NO_PROXY': '*', 'no_proxy': '*'}), patch('m3u8_bridge.gateway.subprocess.Popen') as popen:
            popen.return_value.communicate.return_value = (b'fixture\n__MB_STATUS__200', b'')
            popen.return_value.returncode = 0
            gateway.fetch_remote('job', 'https://media.example.test/segment.ts')
        args = popen.call_args.args[0]
        self.assertEqual(args[args.index('--proxy') + 1], 'socks5h://127.0.0.1:7890')
        self.assertEqual(args[args.index('--noproxy') + 1], '')


class AccessLogTests(unittest.TestCase):
    def handler(self, method, path):
        handler = Handler.__new__(Handler)
        handler.command = method
        handler.path = path
        return handler

    def test_successful_polling_and_segment_requests_are_quiet(self):
        for path in ('/api/jobs', '/api/settings', '/healthz', '/api/session', '/hls/job/resource/segment.ts'):
            with self.subTest(path=path), patch('builtins.print') as printer:
                self.handler('GET', path).log_message('"%s" %s %s', f'GET {path} HTTP/1.1', '200', '-')
                printer.assert_not_called()

    def test_failed_requests_and_mutations_remain_visible(self):
        for method, status in (('GET', '502'), ('GET', '401'), ('POST', '200'), ('DELETE', '200')):
            with self.subTest(method=method, status=status), patch('builtins.print') as printer:
                self.handler(method, '/api/jobs').log_message('"%s" %s %s', f'{method} /api/jobs HTTP/1.1', status, '-')
                printer.assert_called_once()

    def test_protocol_errors_remain_visible(self):
        with patch('builtins.print') as printer:
            self.handler('GET', '/api/jobs').log_message('code %d, message %s', 400, 'Bad request')
            printer.assert_called_once()
