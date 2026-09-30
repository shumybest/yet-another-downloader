import unittest
import json
import os
import signal
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer
from unittest.mock import patch

from m3u8_bridge.server import Engine, activate_desktop, default_settings, engine_health, monitor_desktop_parent, read_settings


class MediaRoutingTests(unittest.TestCase):
    def test_default_settings_do_not_assume_a_local_proxy(self):
        self.assertEqual(default_settings()['proxy'], '')

    def test_desktop_activation_rejects_absent_or_invalid_pid(self):
        with patch.dict(os.environ, {'M3U8_BRIDGE_DESKTOP_PID': ''}):
            self.assertFalse(activate_desktop())
        with patch('m3u8_bridge.server.os.kill') as kill:
            self.assertFalse(activate_desktop('-3'))
            self.assertFalse(activate_desktop('not-a-pid'))
            kill.assert_not_called()

    def test_desktop_activation_signals_valid_pid(self):
        with patch('m3u8_bridge.server.os.kill') as kill:
            self.assertTrue(activate_desktop('4242'))
            kill.assert_called_once_with(4242, signal.SIGUSR1)

    def test_desktop_activation_handles_stale_pid(self):
        with patch('m3u8_bridge.server.os.kill', side_effect=ProcessLookupError):
            self.assertFalse(activate_desktop('4242'))

    def test_managed_engine_stops_after_desktop_parent_disappears(self):
        stopped = []

        def missing_parent(pid, signal_number):
            self.assertEqual((pid, signal_number), (4242, 0))
            raise ProcessLookupError

        monitor_desktop_parent(lambda: stopped.append(True), '4242', interval=0.01, pid_probe=missing_parent)
        self.assertEqual(stopped, [True])

    def test_health_advertises_job_deletion_capability(self):
        health = engine_health()

        self.assertGreaterEqual(health['apiRevision'], 2)
        self.assertIn('jobs.delete', health['capabilities'])

    def test_health_reports_packaged_ffmpeg_from_environment(self):
        with patch.dict(os.environ, {'M3U8_BRIDGE_FFMPEG': '/Applications/yet another downloader.app/Contents/Resources/binaries/ffmpeg'}):
            self.assertEqual(
                engine_health()['ffmpeg'],
                '/Applications/yet another downloader.app/Contents/Resources/binaries/ffmpeg',
            )

    def test_packaged_ffmpeg_overrides_a_stale_saved_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text(json.dumps({'ffmpegPath': '/usr/local/bin/ffmpeg'}))
            with patch('m3u8_bridge.server.settings_path', return_value=path), patch.dict(
                os.environ,
                {'M3U8_BRIDGE_FFMPEG': '/Applications/yet another downloader.app/Contents/Resources/binaries/ffmpeg'},
            ):
                self.assertEqual(
                    read_settings()['ffmpegPath'],
                    '/Applications/yet another downloader.app/Contents/Resources/binaries/ffmpeg',
                )

    def test_delete_keeps_terminal_job_in_memory_when_history_delete_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/video.mp4', 'kind': 'direct'}, 'direct', 'clip', 1, '')
            job['status'] = 'failed'
            engine.jobs[job['id']] = job
            engine.history.upsert(job)

            with patch.object(engine.history, 'delete', side_effect=RuntimeError('database busy')):
                with self.assertRaisesRegex(RuntimeError, 'database busy'):
                    engine.delete_job(job['id'])

            self.assertIn(job['id'], engine.jobs)

    def test_delete_reconciles_terminal_job_missing_from_history(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/video.mp4', 'kind': 'direct'}, 'direct', 'clip', 1, '')
            job['status'] = 'failed'
            engine.jobs[job['id']] = job

            self.assertTrue(engine.delete_job(job['id']))
            self.assertNotIn(job['id'], engine.jobs)

    def test_job_updates_are_persisted_without_capture_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            capture = {'url': 'https://media.example/video.m3u8?token=secret', 'kind': 'hls', 'headers': {'Authorization': 'secret'}}
            job = engine._new_job(capture, 'hls', 'clip', attempt=1, retry_of='')
            engine.jobs[job['id']] = job
            engine._update(job, status='failed', error='network failure', canRetry=True)
            saved = engine.history.load()[0]
            self.assertEqual(saved['status'], 'failed')
            self.assertEqual(saved['title'], 'clip')
            self.assertNotIn('url', saved)
            self.assertNotIn('Authorization', str(saved))
            self.assertEqual(len(saved['sourceFingerprint']), 64)

    def test_progress_persistence_is_throttled_but_terminal_state_is_immediate(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            capture = {'url': 'https://media.example/video.m3u8', 'kind': 'hls'}
            job = engine._new_job(capture, 'hls', 'clip', attempt=1, retry_of='')

            with patch.object(engine.history, 'upsert', wraps=engine.history.upsert) as upsert:
                engine._update(job)
                for downloaded in range(1, 21):
                    engine._update(job, status='downloading', downloadedBytes=downloaded)
                engine._update(job, status='failed', error='network failure')

            self.assertEqual(upsert.call_count, 3)
            saved = engine.history.load()[0]
            self.assertEqual(saved['status'], 'failed')
            self.assertEqual(saved['downloadedBytes'], 20)

    def test_retry_creates_a_new_attempt_when_capture_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            capture = {'url': 'https://media.example/video.m3u8', 'kind': 'hls'}
            source = engine._new_job(capture, 'hls', 'clip', attempt=1, retry_of='')
            source.update(status='failed', canRetry=True)
            engine.jobs[source['id']] = source
            with patch.object(engine, '_run_job'), patch('m3u8_bridge.server.threading.Thread') as thread:
                retry = engine.retry_job(source['id'])
            thread.assert_called_once()
            self.assertNotEqual(retry['id'], source['id'])
            self.assertEqual(retry['attempt'], 2)
            self.assertEqual(retry['retryOf'], source['id'])
            self.assertEqual(retry['status'], 'queued')

    def test_retry_uses_the_latest_concurrency_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            capture = {'url': 'https://media.example/video.m3u8', 'kind': 'hls'}
            source = engine._new_job(capture, 'hls', 'clip', attempt=1, retry_of='')
            source.update(status='failed', canRetry=True)
            engine.jobs[source['id']] = source
            engine.settings['concurrency'] = 12

            with patch('m3u8_bridge.server.threading.Thread') as thread:
                engine.retry_job(source['id'])

            settings_snapshot = thread.call_args.kwargs['args'][2]
            self.assertEqual(settings_snapshot['concurrency'], 12)

    def test_calculates_speed_from_downloaded_byte_samples(self):
        self.assertEqual(Engine.calculate_speed(1_000_000, 3_000_000, 2.0), 1_000_000)
        self.assertEqual(Engine.calculate_speed(10, 10, 2.0), 0)
        self.assertEqual(Engine.calculate_speed(10, 20, 0), 0)

    def test_stale_progress_event_does_not_regress_metrics_or_refresh_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/video.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')
            job.update(downloadedBytes=4096, downloadedFragments=8, totalFragments=100)
            previous_activity = job['_last_activity_mono']

            engine._handle_progress_event(job, {
                'status': 'downloading',
                'downloaded_bytes': 2048,
                'fragment_index': 7,
                'fragment_count': 100,
            })

            self.assertEqual(job['downloadedBytes'], 4096)
            self.assertEqual(job['downloadedFragments'], 8)
            self.assertEqual(job['_last_activity_mono'], previous_activity)

    def test_new_progress_event_is_monotonic_and_refreshes_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/video.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')
            job.update(downloadedBytes=4096, downloadedFragments=8, totalFragments=100)
            previous_activity = job['_last_activity_mono']
            time.sleep(0.01)

            engine._handle_progress_event(job, {
                'status': 'downloading',
                'downloaded_bytes': 8192,
                'fragment_index': 9,
                'fragment_count': 100,
                'speed': 2048,
            })

            self.assertEqual(job['downloadedBytes'], 8192)
            self.assertEqual(job['downloadedFragments'], 9)
            self.assertGreater(job['_last_activity_mono'], previous_activity)
            self.assertEqual(job['speed'], '2 KiB/s')
            self.assertEqual(job['speedBytesPerSecond'], 2048)

    def test_progress_from_a_second_media_stream_is_accumulated(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/video.mpd', 'kind': 'dash'}, 'dash', 'clip', 1, '')

            engine._handle_progress_event(job, {
                'status': 'downloading',
                'filename': 'video-track.mp4.part',
                'downloaded_bytes': 4096,
                'total_bytes': 8192,
                'fragment_index': 8,
                'fragment_count': 10,
            })
            previous_activity = job['_last_activity_mono']
            time.sleep(0.01)
            engine._handle_progress_event(job, {
                'status': 'downloading',
                'filename': 'audio-track.m4a.part',
                'downloaded_bytes': 1024,
                'total_bytes': 2048,
                'fragment_index': 1,
                'fragment_count': 4,
            })

            self.assertEqual(job['downloadedBytes'], 5120)
            self.assertEqual(job['totalBytes'], 10240)
            self.assertEqual(job['downloadedFragments'], 9)
            self.assertEqual(job['totalFragments'], 14)
            self.assertGreater(job['_last_activity_mono'], previous_activity)

    def test_terminal_job_ignores_late_process_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/video.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')
            job.update(status='failed', stallReason='timed out')
            job['_cancel'].set()
            previous_activity = job['_last_activity_mono']

            engine._process_activity(job)

            self.assertEqual(job['stallReason'], 'timed out')
            self.assertEqual(job['_last_activity_mono'], previous_activity)

    def test_public_job_exposes_download_metrics_and_retry_state(self):
        public = Engine.public_job({
            'id': 'job', 'status': 'downloading', 'title': 'clip', 'url': 'https://media.example/clip.m3u8',
            'kind': 'hls', 'outputPath': '', 'progress': 2.0, 'downloadedFragments': 2,
            'totalFragments': 100, 'downloadedBytes': 2048, 'totalBytes': 4096,
            'speed': '1.00 MiB/s', 'error': '', 'lastActivityAt': 1000,
            'stallReason': '', 'attempt': 1, 'retryOf': '', 'canRetry': True,
            'createdAt': 900, 'updatedAt': 1000,
        })
        self.assertEqual(public['downloadedBytes'], 2048)
        self.assertEqual(public['totalBytes'], 4096)
        self.assertTrue(public['canRetry'])

    def test_classifies_common_media_captures(self):
        self.assertEqual(Engine._capture_kind({'url': 'https://media.example/master.m3u8'}), 'hls')
        self.assertEqual(Engine._capture_kind({'url': 'https://media.example/manifest.mpd'}), 'dash')
        self.assertEqual(Engine._capture_kind({'url': 'https://media.example/movie', 'contentType': 'video/mp4'}), 'direct')

    def test_ytdlp_options_preserve_proxy_headers_and_mp4_output(self):
        options = Engine._yt_dlp_options(
            Path('/tmp/output'),
            'clip',
            '/usr/local/bin/ffmpeg',
            {'kind': 'dash', 'headers': {'Referer': 'https://media.example/page', 'Origin': 'https://media.example'}},
            'http://127.0.0.1:7890',
            lambda _event: None,
        )
        self.assertEqual(options['proxy'], 'http://127.0.0.1:7890')
        self.assertEqual(options['http_headers']['Referer'], 'https://media.example/page')
        self.assertEqual(options['http_headers']['Origin'], 'https://media.example')
        self.assertEqual(options['merge_output_format'], 'mp4')
        self.assertEqual(options['concurrent_fragment_downloads'], 8)
        self.assertEqual(options['socket_timeout'], 30)
        self.assertEqual(options['fragment_retries'], 3)
        self.assertIn('fragment', options['retry_sleep_functions'])

    def test_unknown_capture_is_rejected_before_starting_a_job(self):
        with self.assertRaises(ValueError):
            Engine._capture_kind({'url': 'https://media.example/player.js', 'contentType': 'application/javascript'})

    def test_normalizes_non_h264_video_to_playable_mp4(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg is required for media normalization tests')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.avi'
            subprocess.run([
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=5',
                '-t', '1', '-c:v', 'mpeg4', str(source),
            ], check=True)
            output = Engine._normalize_output(source, root, 'normalized', ffmpeg)
            self.assertEqual(output.suffix, '.mp4')
            self.assertTrue(output.is_file())
            self.assertTrue(any(stream.get('codec_type') == 'video' for stream in Engine._probe_streams(output)))

    def test_normalizes_h264_with_incompatible_pixel_format_for_quicklook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.mp4'
            source.write_bytes(b'original')

            def encode(_source, target, _ffmpeg, *_args):
                target.write_bytes(b'normalized')

            with (
                patch.object(Engine, '_probe_streams', return_value=[{
                    'codec_type': 'video',
                    'codec_name': 'h264',
                    'pix_fmt': 'yuv444p',
                    'codec_tag_string': 'avc1',
                }]),
                patch.object(Engine, '_encode_mp4', side_effect=encode) as encoder,
            ):
                output = Engine._normalize_output(source, root, 'normalized', 'ffmpeg')

            encoder.assert_called_once()
            self.assertEqual(output.read_bytes(), b'normalized')

    def test_converts_image_segments_without_sips_and_rejects_html(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg is required for image segment tests')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.png'
            converted = root / 'converted.png'
            subprocess.run([
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=32x18:rate=1',
                '-frames:v', '1', '-f', 'image2', str(source),
            ], check=True)
            Engine._convert_image_segment(source.read_bytes(), root / 'raw.bin', converted, ffmpeg, 147)
            self.assertTrue(converted.is_file())
            self.assertEqual(Engine._image_format(source.read_bytes()), 'PNG')
            with self.assertRaisesRegex(RuntimeError, 'not a supported image'):
                Engine._convert_image_segment(b'<html>429</html>', root / 'bad.bin', root / 'bad.png', ffmpeg, 147)

    def test_png_wrapped_mpegts_segments_preserve_video_and_audio(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg is required for wrapped MPEG-TS tests')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cover = root / 'cover.png'
            transport = root / 'source.ts'
            output = root / 'output.mp4'
            subprocess.run([
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'lavfi', '-i', 'testsrc=size=64x36:rate=10',
                '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=44100',
                '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                '-f', 'mpegts', str(transport),
            ], check=True)
            subprocess.run([
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'lavfi', '-i', 'color=size=64x36:color=black',
                '-frames:v', '1', '-f', 'image2', str(cover),
            ], check=True)
            wrapped = cover.read_bytes() + (b'\xff' * 135) + transport.read_bytes()

            engine = Engine(database_path=root / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/wrapped.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')
            engine.gateway.fetch_remote = lambda _job_id, _url: wrapped

            engine._download_png_segments(
                job,
                [('https://media.example/segment', 1.0)],
                output,
                ffmpeg,
                1,
            )

            streams = Engine._probe_streams(output)
            self.assertTrue(any(stream.get('codec_type') == 'video' for stream in streams))
            self.assertTrue(any(stream.get('codec_type') == 'audio' for stream in streams))

    def test_png_scheduler_stops_inflight_segments_after_one_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/images.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')

            def fetch(_job_id, url):
                if url.endswith('/bad'):
                    raise RuntimeError('simulated bad segment')
                if url.endswith('/hang'):
                    while not job['_cancel'].is_set():
                        time.sleep(0.02)
                    raise RuntimeError('cancelled hanging segment')
                return b'image'

            def convert(_data, _raw, clean, _ffmpeg, _index, _cancel=None):
                clean.write_bytes(b'converted')

            engine.gateway.fetch_remote = fetch
            engine._convert_image_segment = convert
            segments = [(f'https://media.example/{"bad" if index == 0 else "hang" if index == 1 else index}', 0.1) for index in range(40)]
            started = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, 'Could not normalize PNG segment'):
                engine._download_png_segments(job, segments, Path(directory) / 'clip.mp4', 'ffmpeg', 8)
            self.assertLess(time.monotonic() - started, 5)
            self.assertTrue(job['_cancel'].is_set())

    def test_png_scheduler_observes_cancel_when_all_futures_are_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/images.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')
            fetch_started = threading.Event()
            release_fetch = threading.Event()
            errors = []

            def fetch(_job_id, _url):
                fetch_started.set()
                release_fetch.wait(5)
                raise RuntimeError('released test segment')

            def run_download():
                try:
                    engine._download_png_segments(
                        job,
                        [('https://media.example/hang', 0.1)],
                        Path(directory) / 'clip.mp4',
                        'ffmpeg',
                        1,
                    )
                except BaseException as error:
                    errors.append(error)

            engine.gateway.fetch_remote = fetch
            worker = threading.Thread(target=run_download)
            worker.start()
            self.assertTrue(fetch_started.wait(1), 'segment fetch did not start')
            try:
                job['_cancel'].set()
                worker.join(timeout=0.75)
                self.assertFalse(worker.is_alive(), 'PNG scheduler ignored cancellation while waiting for a future')
            finally:
                release_fetch.set()
                worker.join(timeout=2)
            self.assertTrue(errors)
            self.assertIn('cancel', str(errors[0]).lower())

    def test_png_scheduler_has_its_own_no_progress_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/images.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')
            fetch_started = threading.Event()
            release_fetch = threading.Event()
            errors = []

            def fetch(_job_id, _url):
                fetch_started.set()
                release_fetch.wait(5)
                raise RuntimeError('released test segment')

            def run_download():
                try:
                    engine._download_png_segments(
                        job,
                        [('https://media.example/hang', 0.1)],
                        Path(directory) / 'clip.mp4',
                        'ffmpeg',
                        1,
                    )
                except BaseException as error:
                    errors.append(error)

            engine.gateway.fetch_remote = fetch
            worker = threading.Thread(target=run_download)
            with patch('m3u8_bridge.server.STALL_FAILURE_SECONDS', 0.1, create=True):
                worker.start()
                self.assertTrue(fetch_started.wait(1), 'segment fetch did not start')
                try:
                    worker.join(timeout=0.75)
                    self.assertFalse(worker.is_alive(), 'PNG scheduler has no independent no-progress timeout')
                finally:
                    release_fetch.set()
                    worker.join(timeout=2)
            self.assertTrue(errors)
            self.assertIn('no progress', str(errors[0]).lower())
            self.assertTrue(job['error'])
            self.assertEqual(job['status'], 'failed')

    def test_png_progress_includes_downloaded_bytes_and_speed(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/images.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')
            payloads = {
                'https://media.example/one': b'a' * 1024,
                'https://media.example/two': b'b' * 2048,
            }

            engine.gateway.fetch_remote = lambda _job_id, url: payloads[url]
            engine._convert_image_segment = lambda _data, _raw, clean, _ffmpeg, _index, _cancel=None: clean.write_bytes(b'converted')

            def run_ffmpeg(args, **_kwargs):
                Path(args[-1]).write_bytes(b'mp4')
                return type('Result', (), {'returncode': 0, 'stderr': ''})()

            with patch.object(engine, '_run_cancellable_process', side_effect=run_ffmpeg):
                engine._download_png_segments(
                    job,
                    list((url, 0.1) for url in payloads),
                    Path(directory) / 'clip.mp4',
                    'ffmpeg',
                    2,
                )

            self.assertEqual(job['downloadedBytes'], 3072)
            self.assertTrue(job['speed'])

    def test_png_mux_process_is_terminated_when_job_is_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'mux-started'
            release = root / 'release-mux'
            fake_ffmpeg = root / 'fake-ffmpeg'
            fake_ffmpeg.write_text(
                '#!/bin/sh\n'
                f': > "{marker}"\n'
                f'while [ ! -f "{release}" ]; do sleep 0.05; done\n'
            )
            fake_ffmpeg.chmod(0o755)

            engine = Engine(database_path=root / 'history.sqlite3')
            job = engine._new_job({'url': 'https://media.example/images.m3u8', 'kind': 'hls'}, 'hls', 'clip', 1, '')
            engine.gateway.fetch_remote = lambda _job_id, _url: b'image'
            engine._convert_image_segment = lambda _data, _raw, clean, _ffmpeg, _index, _cancel=None: clean.write_bytes(b'converted')
            errors = []

            def download():
                try:
                    engine._download_png_segments(
                        job,
                        [('https://media.example/one', 0.1)],
                        root / 'clip.mp4',
                        str(fake_ffmpeg),
                        1,
                    )
                except BaseException as error:
                    errors.append(error)

            worker = threading.Thread(target=download)
            worker.start()
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), 'mux process did not start')
            try:
                job['_cancel'].set()
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive(), 'PNG mux ignored cancellation')
            finally:
                release.touch()
                worker.join(timeout=2)
            self.assertTrue(errors)
            self.assertIn('cancel', str(errors[0]).lower())

    def test_png_job_cannot_overwrite_a_watchdog_failure_with_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            capture = {'url': 'https://media.example/images.m3u8', 'kind': 'hls'}
            job = engine._new_job(capture, 'hls', 'clip', 1, '')
            engine.jobs[job['id']] = job

            def expire_job(*_args, **_kwargs):
                job['_watchdog_expired'] = True
                job['_cancel'].set()
                engine._update(job, status='failed', error='stalled', canRetry=True)

            with (
                patch.object(engine.gateway, 'detect_png_segments', return_value=[('https://media.example/one', 0.1)]),
                patch.object(engine, '_download_png_segments', side_effect=expire_job),
                patch.object(engine, '_validate') as validate,
            ):
                engine._run_job(job, {'capture': capture, 'filename': 'clip', 'outputDir': directory}, {'ffmpegPath': 'ffmpeg', 'concurrency': 8})

            self.assertEqual(job['status'], 'failed')
            self.assertEqual(job['error'], 'stalled')
            validate.assert_not_called()

    def test_png_segment_failure_is_reported_as_failed_not_user_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            capture = {'url': 'https://media.example/images.m3u8', 'kind': 'hls'}
            job = engine._new_job(capture, 'hls', 'clip', 1, '')
            engine.jobs[job['id']] = job

            with (
                patch.object(engine.gateway, 'detect_png_segments', return_value=[('https://media.example/bad', 0.1)]),
                patch.object(engine.gateway, 'fetch_remote', side_effect=RuntimeError('HTTP 429')),
                patch('m3u8_bridge.server.retry_delay', return_value=0.01),
            ):
                engine._run_job(job, {'capture': capture, 'outputDir': directory}, {'ffmpegPath': 'ffmpeg', 'concurrency': 8})

            self.assertEqual(job['status'], 'failed')
            self.assertIn('HTTP 429', job['error'])

    def test_failed_png_validation_does_not_publish_a_broken_final_file(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            capture = {'url': 'https://media.example/images.m3u8', 'kind': 'hls'}
            job = engine._new_job(capture, 'hls', 'clip', 1, '')
            engine.jobs[job['id']] = job

            def create_invalid_output(_job, _segments, output_path, _ffmpeg, _concurrency):
                output_path.write_bytes(b'invalid')

            with (
                patch.object(engine.gateway, 'detect_png_segments', return_value=[('https://media.example/one', 0.1)]),
                patch.object(engine, '_download_png_segments', side_effect=create_invalid_output),
                patch.object(engine, '_validate', side_effect=RuntimeError('invalid media')),
            ):
                engine._run_job(job, {'capture': capture, 'filename': 'clip', 'outputDir': directory}, {'ffmpegPath': 'ffmpeg', 'concurrency': 8})

            self.assertEqual(job['status'], 'failed')
            self.assertFalse((Path(directory) / 'clip.mp4').exists())

    def test_committing_output_preserves_an_existing_download(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            root = Path(directory)
            existing = root / 'clip.mp4'
            staged = root / '.staged.mp4'
            existing.write_bytes(b'first')
            staged.write_bytes(b'second')

            committed = engine._commit_output(staged, root, 'clip')

            self.assertEqual(existing.read_bytes(), b'first')
            self.assertEqual(committed.name, 'clip (2).mp4')
            self.assertEqual(committed.read_bytes(), b'second')

    def test_direct_media_curl_fallback_downloads_and_validates(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg or not shutil.which('curl'):
            self.skipTest('ffmpeg and curl are required for direct fallback tests')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.avi'
            subprocess.run([
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=5',
                '-t', '1', '-c:v', 'mpeg4', str(source),
            ], check=True)
            handler = partial(SimpleHTTPRequestHandler, directory=directory)
            server = TCPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                output = Engine()._download_direct_fallback(
                    {'id': 'direct-test'},
                    {'url': f'http://127.0.0.1:{server.server_address[1]}/source.avi', 'kind': 'direct'},
                    root,
                    'direct',
                    ffmpeg,
                    '',
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            Engine._validate(output, ffmpeg)
            self.assertEqual(output.suffix, '.mp4')

    def test_direct_media_fallback_can_be_cancelled_while_receiving(self):
        request_started = threading.Event()
        release_response = threading.Event()

        class SlowHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                request_started.set()
                self.send_response(200)
                self.end_headers()
                release_response.wait(5)
                try:
                    self.wfile.write(b'not-a-video')
                except BrokenPipeError:
                    pass

            def log_message(self, _format, *_args):
                return

        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            job = engine._new_job({'url': 'http://127.0.0.1/video.mp4', 'kind': 'direct'}, 'direct', 'clip', 1, '')
            server = TCPServer(('127.0.0.1', 0), SlowHandler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            errors = []

            def download():
                try:
                    engine._download_direct_fallback(
                        job,
                        {'url': f'http://127.0.0.1:{server.server_address[1]}/video.mp4', 'kind': 'direct'},
                        Path(directory),
                        'direct',
                        shutil.which('ffmpeg') or 'ffmpeg',
                        '',
                    )
                except BaseException as error:
                    errors.append(error)

            worker = threading.Thread(target=download)
            worker.start()
            self.assertTrue(request_started.wait(2), 'direct download did not reach the test server')
            try:
                job['_cancel'].set()
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive(), 'direct fallback ignored cancellation')
            finally:
                release_response.set()
                worker.join(timeout=3)
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=3)
            self.assertTrue(errors)
            self.assertIn('cancel', str(errors[0]).lower())


if __name__ == '__main__':
    unittest.main()
