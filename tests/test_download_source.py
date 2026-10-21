import unittest
from unittest.mock import patch
from pathlib import Path
import shutil
import subprocess
import tempfile

from m3u8_bridge.download_source import download_source, youtube_page_url
from m3u8_bridge.server import Engine


class DownloadSourceTests(unittest.TestCase):
    def setUp(self):
        # Reserved fixture domains exercise the same host/path checks as production.
        self.enterContext(patch('m3u8_bridge.download_source.YOUTUBE_HOSTS', {'www.example.test', 'example.test'}))
        self.enterContext(patch('m3u8_bridge.download_source.YOUTUBE_SHORT_HOST', 'short.example.test'))
        self.enterContext(patch('m3u8_bridge.download_source.YOUTUBE_CANONICAL_HOST', 'www.example.test'))
        self.enterContext(patch('m3u8_bridge.download_source.YOUTUBE_MEDIA_SUFFIX', '.media.example.test'))
        self.page = 'https://www.example.test/watch?v=abcdefghijk'

    def test_canonical_watch_shorts_and_short_links(self):
        self.assertEqual(youtube_page_url(self.page + '&list=private'), self.page)
        self.assertEqual(youtube_page_url('https://example.test/shorts/abcdefghijk'), self.page)
        self.assertEqual(youtube_page_url('https://short.example.test/abcdefghijk?t=123'), self.page)

    def test_rejects_untrusted_hosts_invalid_ids_and_credentials(self):
        for url in ('https://www.example.test.evil.test/watch?v=abcdefghijk',
                    'https://example.test/watch?v=bad', 'https://example.test/playlist',
                    self.page.replace('://', '://fixture-user:fixture-password@'),
                    'ftp://example.test/watch?v=abcdefghijk'):
            self.assertIsNone(youtube_page_url(url))

    def test_cdn_single_track_uses_page_without_forwarding_cdn_credentials_or_range(self):
        capture = {'url': 'https://r1.media.example.test/videoplayback?id=123&range=0-6166',
                   'pageUrl': self.page, 'kind': 'direct', 'cookie': 'fixture-only',
                   'headers': {'Range': 'bytes=0-6166', 'Host': 'r1.media.example.test',
                               'Authorization': 'fixture-only', 'Cookie': 'fixture-only',
                               'Origin': 'https://cdn.example.test', 'User-Agent': 'fixture-agent'}}
        source, context, page = download_source(capture)
        self.assertEqual(source, self.page)
        self.assertTrue(page)
        self.assertEqual(context['headers'], {'User-Agent': 'fixture-agent', 'Referer': self.page})
        self.assertNotIn('cookie', context)
        self.assertIn('Range', capture['headers'])

    def test_direct_page_drops_tracking_and_is_not_a_curl_fallback(self):
        source, context, page = download_source({'url': self.page + '&list=123'})
        self.assertEqual(source, self.page)
        self.assertTrue(page)
        self.assertEqual(context['url'], self.page)

    def test_arbitrary_media_is_not_redirected_to_an_unrelated_page(self):
        capture = {'url': 'https://other.example.test/movie.mp4', 'pageUrl': self.page}
        source, context, page = download_source(capture)
        self.assertEqual((source, context, page), (capture['url'], capture, False))

    def test_cdn_without_valid_page_requests_recapture_instead_of_incomplete_track(self):
        with self.assertRaisesRegex(ValueError, 'YouTube.*page URL'):
            download_source({'url': 'https://r1.media.example.test/videoplayback?range=0-6166'})

    def test_page_and_cdn_are_routed_before_explicit_media_kind(self):
        self.assertEqual(Engine._capture_kind({'url': self.page}), 'direct')
        self.assertEqual(Engine._capture_kind({'url': self.page, 'kind': 'hls'}), 'direct')
        self.assertEqual(Engine._capture_kind({'url': 'https://r1.media.example.test/videoplayback',
                                              'pageUrl': self.page, 'contentType': 'audio/mp4'}), 'direct')

    def test_site_extractor_failure_is_not_downloaded_as_html_by_curl(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(database_path=Path(directory) / 'history.sqlite3')
            capture = {'url': self.page}
            job = engine._new_job(capture, 'direct', 'clip', 1, '')
            with patch('yt_dlp.YoutubeDL') as downloader, patch.object(engine, '_download_direct_fallback') as fallback:
                downloader.return_value.__enter__.return_value.extract_info.side_effect = RuntimeError('site extraction failed')
                engine._run_job(job, {'outputDir': directory}, {**engine.settings, 'ffmpegPath': 'ffmpeg'})
            fallback.assert_not_called()
            self.assertEqual(job['status'], 'failed')
            self.assertEqual(job['error'], 'site extraction failed')
            self.assertFalse(list(Path(directory).glob('*.mp4')))
            engine._watchdog_stop.set()

    def test_cdn_capture_downloads_merged_video_and_audio_and_validates_final_output(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg and ffprobe required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'fixture.mp4'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=5',
                            '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(fixture)], check=True)
            engine = Engine(database_path=root / 'history.sqlite3')
            capture = {'url': 'https://r1.media.example.test/videoplayback?range=0-6166',
                       'pageUrl': self.page, 'kind': 'direct', 'headers': {'Range': 'bytes=0-6166'}}
            job = engine._new_job(capture, 'direct', 'clip', 1, '')

            def extract(url, download):
                self.assertEqual(url, self.page)
                self.assertTrue(download)
                output = Path(options['outtmpl'].replace('%(ext)s', 'mp4'))
                shutil.copyfile(fixture, output)
                # A leftover prepared audio path must not win over the final file.
                output.with_suffix('.m4a').write_bytes(b'incomplete-audio')
                return {'filepath': str(output)}

            with patch('yt_dlp.YoutubeDL') as downloader, patch.object(engine, '_download_direct_fallback') as fallback:
                client = downloader.return_value.__enter__.return_value
                client.extract_info.side_effect = extract
                client.prepare_filename.side_effect = lambda info: str(Path(info['filepath']).with_suffix('.m4a'))
                options = {}

                def save_options(value):
                    options.update(value)
                    return downloader.return_value

                downloader.side_effect = save_options
                engine._run_job(job, {'outputDir': directory, 'proxy': ''}, {**engine.settings, 'ffmpegPath': ffmpeg})

            self.assertEqual(job['status'], 'completed', job['error'])
            fallback.assert_not_called()
            self.assertNotIn('Range', options['http_headers'])
            output = Path(job['outputPath'])
            streams = Engine._probe_streams(output)
            self.assertEqual({stream['codec_type'] for stream in streams}, {'video', 'audio'})
            self.assertFalse(list(root.glob('.m3u8-bridge-*')))
            engine._watchdog_stop.set()


if __name__ == '__main__':
    unittest.main()
