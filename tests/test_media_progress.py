import unittest
import shutil
import subprocess
import tempfile
import threading
import sys
from pathlib import Path
from m3u8_bridge.media_progress import MediaProgress
from m3u8_bridge.server import Engine


class MediaProgressTests(unittest.TestCase):
    def test_ytdlp_retry_callback_accepts_zero_based_keyword(self):
        from m3u8_bridge.server import retry_delay
        from yt_dlp.utils import RetryManager
        from unittest.mock import patch
        self.assertEqual(retry_delay(n=0), .5)
        self.assertEqual(retry_delay(n=3), 4)
        self.assertEqual(retry_delay(1), .5)
        with patch('yt_dlp.utils._utils.time.sleep') as sleep:
            RetryManager.report_retry(RuntimeError('fixture'), 1, 3, sleep_func=retry_delay,
                                      info=lambda _: None, warn=lambda _: None)
        sleep.assert_called_once_with(.5)

    def test_processing_failure_retains_download_without_publishing_it(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = Engine(database_path=root / 'history.sqlite3')
            capture = {'url': 'https://media.example.test/clip.mp4', 'kind': 'direct', 'title': 'clip'}
            job = engine._new_job(capture, 'direct', 'clip', 1, '')
            def extract(_url, download):
                path = Path(options['outtmpl'].replace('%(ext)s', 'mp4'))
                path.write_bytes(b'complete-downloaded-fixture')
                return {'filepath': str(path)}
            def normalize(source, output_dir, stem, ffmpeg, cancel, reporter):
                reporter.start('transcoding', 100)
                raise RuntimeError('fixture processing failure')
            options = {}
            with patch('yt_dlp.YoutubeDL') as downloader, patch.object(engine, '_normalize_output', side_effect=normalize):
                downloader.side_effect = lambda value: (options.update(value) or downloader.return_value)
                client = downloader.return_value.__enter__.return_value
                client.extract_info.side_effect = extract
                client.prepare_filename.side_effect = lambda info: info['filepath']
                engine._run_job(job, {'outputDir': directory}, {**engine.settings, 'ffmpegPath': 'ffmpeg'})
            self.assertEqual(job['status'], 'failed')
            self.assertIn('已下载的文件已保留', job['error'])
            self.assertFalse((root / 'clip.mp4').exists())
            self.assertEqual(next(root.glob('.m3u8-bridge-*/clip.mp4')).read_bytes(), b'complete-downloaded-fixture')
            engine._watchdog_stop.set()

    def test_advancing_process_outlives_old_total_limit(self):
        reporter = MediaProgress(lambda **_: None, lambda: None)
        reporter.start('transcoding', 10)
        code = "import time; [ (print(f'out_time_us={i*1000000}\\nprogress=continue', flush=True), time.sleep(.08)) for i in range(6)]"
        result = Engine._run_cancellable_process([sys.executable, '-c', code], .15, on_progress=reporter, idle_timeout=.3)
        self.assertEqual(result.returncode, 0)

    def test_repeated_progress_without_advancement_times_out(self):
        reporter = MediaProgress(lambda **_: None, lambda: None)
        reporter.start('transcoding', 10)
        code = "import time; [(print('out_time_us=0\\nprogress=continue', flush=True), time.sleep(.05)) for _ in range(100)]"
        with self.assertRaisesRegex(RuntimeError, 'no processing progress'):
            Engine._run_cancellable_process([sys.executable, '-c', code], 10, on_progress=reporter, idle_timeout=.3)

    def test_processing_cancel_remains_responsive(self):
        cancel = threading.Event()
        timer = threading.Timer(.2, cancel.set)
        timer.start()
        try:
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                Engine._run_cancellable_process([sys.executable, '-c', 'import time; time.sleep(10)'],
                                                10, cancel, idle_timeout=1)
        finally:
            timer.cancel()

    def test_compatible_codec_in_other_container_is_remuxed_without_reencoding(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'clip.ts'
            source.write_bytes(b'fixture')
            streams = [{'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'duration': '100'}]
            def run(args, **kwargs):
                self.assertIn('copy', args)
                Path(args[-1]).write_bytes(b'remuxed')
                return subprocess.CompletedProcess(args, 0, '', '')
            with patch.object(Engine, '_probe_streams', return_value=streams), patch.object(Engine, '_run_cancellable_process', side_effect=run):
                Engine._normalize_output(source, Path(directory), 'clip', 'ffmpeg')
    def test_real_transcode_updates_before_process_finishes_and_still_validates(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg/ffprobe required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.mkv'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x96:rate=10',
                            '-t', '3', '-c:v', 'ffv1', str(source)], check=True)
            updates = []
            reporter = MediaProgress(lambda **value: updates.append(value), lambda: None)
            reporter.start('transcoding', 3)
            target = root / 'output.mp4'
            result = Engine._run_cancellable_process([
                ffmpeg, '-v', 'error', '-re', '-i', str(source), '-progress', 'pipe:1', '-nostats',
                '-c:v', 'libx264', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p', '-y', str(target)
            ], 15, threading.Event(), reporter)
            self.assertEqual(result.returncode, 0, result.stderr)
            values = [value['processingProgress'] for value in updates if value.get('processingProgress') is not None]
            self.assertGreater(len(values), 2)
            self.assertTrue(any(0 < value < 90 for value in values))
            self.assertEqual(values[-1], 99.9)
            Engine._validate(target, ffmpeg, on_progress=reporter)
            self.assertTrue(any(value.get('processingStage') == 'scanning' for value in updates))

    def test_partial_records_unknown_values_and_real_percentage(self):
        updates = []
        reporter = MediaProgress(lambda **value: updates.append(value), lambda: None)
        reporter.start('transcoding', 100)
        reporter.feed(b'out_time_us=25000000\nspeed=0.5x\nprogress=con')
        self.assertIsNone(updates[-1]['processingProgress'])
        reporter.feed(b'out_time_us=25000000\nspeed=0.5x\nprogress=continue\n')
        self.assertEqual(updates[-1]['processingProgress'], 25)
        self.assertEqual(updates[-1]['processingSeconds'], 25)
        self.assertEqual(updates[-1]['processingSpeed'], '0.5x')
        reporter.feed(b'out_time_us=25000000\nspeed=0.5x\nprogress=continue\nout_time_us=N/A\nspeed=N/A\nprogress=end\n')
        self.assertEqual(updates[-1]['processingProgress'], 99.9)

    def test_no_duration_does_not_invent_percentage(self):
        updates = []
        reporter = MediaProgress(lambda **value: updates.append(value), lambda: None)
        reporter.start('merging', 0)
        reporter.feed(b'out_time_us=2000000\nprogress=continue\n')
        self.assertIsNone(updates[-1]['processingProgress'])
        self.assertEqual(updates[-1]['processingSeconds'], 2)
