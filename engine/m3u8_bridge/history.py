from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


INTERRUPTED_ERROR = '引擎重启时任务中断，请重新捕获资源后重试'

_COLUMNS = (
    'id', 'status', 'title', 'kind', 'output_path', 'progress',
    'downloaded_fragments', 'total_fragments', 'downloaded_bytes',
    'total_bytes', 'speed', 'error', 'last_activity_at', 'stall_reason',
    'attempt', 'retry_of', 'source_fingerprint', 'created_at', 'updated_at',
)


def _now_ms() -> int:
    return int(time.time() * 1000)


class HistoryStore:
    """Persist non-secret job metadata while keeping captures in memory."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.lock, self._connection() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    kind TEXT,
                    output_path TEXT NOT NULL DEFAULT '',
                    progress REAL NOT NULL DEFAULT 0,
                    downloaded_fragments INTEGER NOT NULL DEFAULT 0,
                    total_fragments INTEGER NOT NULL DEFAULT 0,
                    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    speed TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    last_activity_at INTEGER NOT NULL DEFAULT 0,
                    stall_reason TEXT NOT NULL DEFAULT '',
                    attempt INTEGER NOT NULL DEFAULT 1,
                    retry_of TEXT NOT NULL DEFAULT '',
                    source_fingerprint TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            ''')

    @staticmethod
    def _values(job: dict) -> tuple:
        return (
            job.get('id', ''),
            job.get('status', 'queued'),
            job.get('title', 'video'),
            job.get('kind'),
            job.get('outputPath', ''),
            float(job.get('progress', 0) or 0),
            int(job.get('downloadedFragments', 0) or 0),
            int(job.get('totalFragments', 0) or 0),
            int(job.get('downloadedBytes', 0) or 0),
            int(job.get('totalBytes', 0) or 0),
            job.get('speed', '') or '',
            job.get('error', '') or '',
            int(job.get('lastActivityAt', 0) or 0),
            job.get('stallReason', '') or '',
            int(job.get('attempt', 1) or 1),
            job.get('retryOf', '') or '',
            job.get('sourceFingerprint', '') or '',
            int(job.get('createdAt', 0) or 0),
            int(job.get('updatedAt', 0) or 0),
        )

    def upsert(self, job: dict) -> None:
        placeholders = ', '.join('?' for _ in _COLUMNS)
        assignments = ', '.join(f'{column}=excluded.{column}' for column in _COLUMNS[1:])
        sql = f'INSERT INTO jobs ({", ".join(_COLUMNS)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {assignments}'
        with self.lock, self._connection() as connection:
            connection.execute(sql, self._values(job))

    @staticmethod
    def _public(row: sqlite3.Row) -> dict:
        return {
            'id': row['id'],
            'status': row['status'],
            'title': row['title'],
            'kind': row['kind'],
            'outputPath': row['output_path'],
            'progress': row['progress'],
            'downloadedFragments': row['downloaded_fragments'],
            'totalFragments': row['total_fragments'],
            'downloadedBytes': row['downloaded_bytes'],
            'totalBytes': row['total_bytes'],
            'speed': row['speed'],
            'error': row['error'],
            'lastActivityAt': row['last_activity_at'],
            'stallReason': row['stall_reason'],
            'attempt': row['attempt'],
            'retryOf': row['retry_of'],
            'sourceFingerprint': row['source_fingerprint'],
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at'],
        }

    def load(self) -> list[dict]:
        with self.lock, self._connection() as connection:
            rows = connection.execute('SELECT * FROM jobs ORDER BY created_at DESC').fetchall()
        return [self._public(row) for row in rows]

    def mark_interrupted(self, now: int | None = None) -> int:
        timestamp = now if now is not None else _now_ms()
        active = ('queued', 'probing', 'downloading', 'muxing', 'validating')
        marks = ', '.join('?' for _ in active)
        with self.lock, self._connection() as connection:
            cursor = connection.execute(
                f'''UPDATE jobs
                    SET status='failed', error=?, stall_reason='',
                        speed='', updated_at=?, last_activity_at=?
                    WHERE status IN ({marks})''',
                (INTERRUPTED_ERROR, timestamp, timestamp, *active),
            )
            return cursor.rowcount

    def delete(self, job_id: str) -> bool:
        with self.lock, self._connection() as connection:
            cursor = connection.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            return cursor.rowcount == 1

    def clear_completed(self) -> int:
        with self.lock, self._connection() as connection:
            cursor = connection.execute("DELETE FROM jobs WHERE status='completed'")
            return cursor.rowcount
