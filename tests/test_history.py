import tempfile
import unittest
from pathlib import Path

from m3u8_bridge.history import HistoryStore


def job(job_id: str, status: str = 'completed') -> dict:
    return {
        'id': job_id,
        'status': status,
        'title': 'clip',
        'url': 'https://media.example/video.m3u8',
        'kind': 'hls',
        'outputPath': '/tmp/example/Downloads/clip.mp4',
        'progress': 100.0,
        'downloadedFragments': 10,
        'totalFragments': 10,
        'downloadedBytes': 1024,
        'totalBytes': 2048,
        'speed': '1.25 MiB/s',
        'error': '',
        'lastActivityAt': 1002,
        'stallReason': '',
        'attempt': 1,
        'retryOf': '',
        'createdAt': 1000,
        'updatedAt': 1002,
    }


class HistoryStoreTests(unittest.TestCase):
    def test_upsert_and_load_preserve_public_fields_without_url(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / 'history.sqlite3')
            store.upsert(job('one'))

            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]['id'], 'one')
            self.assertEqual(loaded[0]['downloadedBytes'], 1024)
            self.assertNotIn('url', loaded[0])

    def test_mark_interrupted_converts_active_jobs_to_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / 'history.sqlite3')
            store.upsert(job('active', 'downloading'))
            store.upsert(job('done', 'completed'))

            changed = store.mark_interrupted(now=2000)
            loaded = {item['id']: item for item in store.load()}

            self.assertEqual(changed, 1)
            self.assertEqual(loaded['active']['status'], 'failed')
            self.assertEqual(loaded['active']['error'], '引擎重启时任务中断，请重新捕获资源后重试')
            self.assertEqual(loaded['done']['status'], 'completed')

    def test_delete_and_clear_completed_are_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / 'history.sqlite3')
            store.upsert(job('one'))
            store.upsert(job('two', 'failed'))
            store.upsert(job('three', 'completed'))

            self.assertTrue(store.delete('two'))
            self.assertFalse(store.delete('missing'))
            self.assertEqual(store.clear_completed(), 2)
            self.assertEqual(store.load(), [])


if __name__ == '__main__':
    unittest.main()
