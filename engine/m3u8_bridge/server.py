from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .gateway import HLSGateway
from .history import HistoryStore


ROOT = Path(__file__).resolve().parents[2]
PROGRESS_PERSIST_INTERVAL = 0.5
SCHEDULER_POLL_SECONDS = 0.25
STALL_WARNING_SECONDS = 90.0
STALL_FAILURE_SECONDS = 180.0
ENGINE_API_REVISION = 2
ENGINE_CAPABILITIES = ('jobs.delete', 'jobs.retry', 'jobs.clear-completed', 'app.activate')
for candidate in (ROOT / 'vendor' / 'yt-dlp', ROOT.parent / 'yt-dlp'):
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))


def configured_ffmpeg_path() -> str:
    return os.environ.get('M3U8_BRIDGE_FFMPEG') or shutil.which('ffmpeg') or ''


def default_settings() -> dict:
    return {
        'outputDir': str(Path.home() / 'Downloads'),
        'proxy': '',
        'concurrency': 8,
        'ffmpegPath': configured_ffmpeg_path(),
        'pythonPath': sys.executable,
    }


def settings_path() -> Path:
    return Path.home() / 'Library' / 'Application Support' / 'm3u8-bridge' / 'settings.json'


def history_path() -> Path:
    return Path(os.environ.get('M3U8_BRIDGE_HISTORY_DB') or (Path.home() / 'Library' / 'Application Support' / 'm3u8-bridge' / 'history.sqlite3'))


def read_settings() -> dict:
    defaults = default_settings()
    path = settings_path()
    try:
        stored = json.loads(path.read_text())
        defaults.update({key: value for key, value in stored.items() if key in defaults})
    except (OSError, ValueError):
        pass
    if os.environ.get('M3U8_BRIDGE_FFMPEG'):
        defaults['ffmpegPath'] = os.environ['M3U8_BRIDGE_FFMPEG']
    return defaults


def retry_delay(attempt: int) -> float:
    """Bound retry backoff so a bad proxy cannot leave a job apparently frozen."""
    return min(4.0, 0.5 * (2 ** max(0, int(attempt) - 1)))


def activate_desktop(pid_value: str | None = None) -> bool:
    """Signal only the desktop PID explicitly supplied when the engine started."""
    value = pid_value if pid_value is not None else os.environ.get('M3U8_BRIDGE_DESKTOP_PID', '')
    try:
        pid = int(value)
        if pid <= 1:
            return False
        os.kill(pid, signal.SIGUSR1)
        return True
    except (TypeError, ValueError, OSError):
        return False


def monitor_desktop_parent(
    stop_server,
    pid_value: str | None = None,
    interval: float = 1.0,
    pid_probe=os.kill,
) -> None:
    """Stop a managed sidecar after its desktop parent disappears."""
    value = pid_value if pid_value is not None else os.environ.get('M3U8_BRIDGE_DESKTOP_PID', '')
    try:
        pid = int(value)
        if pid <= 1:
            return
    except (TypeError, ValueError):
        return
    while True:
        try:
            pid_probe(pid, 0)
        except OSError:
            stop_server()
            return
        time.sleep(max(0.05, interval))


def _yt_dlp_version() -> str | None:
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:
        return None


def engine_health() -> dict:
    return {
        'ok': True,
        'version': __version__,
        'apiRevision': ENGINE_API_REVISION,
        'capabilities': list(ENGINE_CAPABILITIES),
        'ffmpeg': configured_ffmpeg_path(),
        'ytDlp': _yt_dlp_version(),
    }


class Engine:
    def __init__(self, database_path: Path | None = None, recover: bool = False) -> None:
        self.settings = read_settings()
        self.settings_lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.captures: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.output_lock = threading.RLock()
        self.token = uuid.uuid4().hex + uuid.uuid4().hex
        self.gateway = HLSGateway()
        self.history = HistoryStore(database_path or history_path())
        if recover:
            self.history.mark_interrupted()
            self._load_history()
            self._watchdog_stop = threading.Event()
            threading.Thread(target=self._watchdog, name='m3u8-job-watchdog', daemon=True).start()
        else:
            self._watchdog_stop = threading.Event()

    def _load_history(self) -> None:
        with self.lock:
            for saved in self.history.load():
                saved['url'] = ''
                saved['_capture'] = None
                saved['_cancel'] = threading.Event()
                saved['_last_activity_mono'] = time.monotonic()
                saved['_last_persist_mono'] = None
                saved['_internal_abort'] = False
                saved['canRetry'] = False
                self.jobs[saved['id']] = saved

    @staticmethod
    def _source_fingerprint(url: str) -> str:
        return hashlib.sha256(url.encode('utf-8')).hexdigest()

    @staticmethod
    def public_job(job: dict) -> dict:
        fields = (
            'id', 'status', 'title', 'url', 'kind', 'outputPath', 'progress',
            'downloadedFragments', 'totalFragments', 'downloadedBytes', 'totalBytes',
            'speed', 'speedBytesPerSecond', 'error', 'lastActivityAt', 'stallReason', 'attempt', 'retryOf',
            'canRetry', 'createdAt', 'updatedAt',
        )
        return {key: job[key] for key in fields if key in job}

    @staticmethod
    def calculate_speed(previous_bytes: int, current_bytes: int, elapsed: float) -> int:
        if elapsed <= 0 or current_bytes <= previous_bytes:
            return 0
        return int((current_bytes - previous_bytes) / elapsed)

    @staticmethod
    def format_speed(bytes_per_second: int) -> str:
        if bytes_per_second <= 0:
            return ''
        if bytes_per_second >= 1024 * 1024:
            return f'{bytes_per_second / 1024 / 1024:.2f} MiB/s'
        return f'{bytes_per_second / 1024:.0f} KiB/s'

    @staticmethod
    def _capture_kind(capture: dict) -> str:
        explicit = str(capture.get('kind') or '').lower()
        if explicit in {'hls', 'dash', 'direct'}:
            return explicit
        url = str(capture.get('url') or '')
        content_type = str(capture.get('contentType') or capture.get('type') or '').split(';', 1)[0].strip().lower()
        if re.search(r'\.m3u8(?:$|[?#])', url, re.IGNORECASE) or 'mpegurl' in content_type:
            return 'hls'
        if re.search(r'\.mpd(?:$|[?#])', url, re.IGNORECASE) or content_type == 'application/dash+xml':
            return 'dash'
        if re.search(r'\.(?:ts|m4s|cmfv|cmfa|aac|vtt|key)(?:$|[?#])', url, re.IGNORECASE) or re.search(r'(?:^|[\/_-])(?:segment|chunk|frag|fragment|init)(?:[\/_?=-]|$)', url, re.IGNORECASE) or content_type in {'video/mp2t', 'video/iso.segment', 'audio/aac'}:
            raise ValueError('Streaming fragments are not standalone video resources')
        if content_type.startswith('video/') or re.search(r'\.(?:mp4|m4v|mov|webm|mkv|flv|f4v|mpeg|mpg|ogv|3gp)(?:$|[?#])', url, re.IGNORECASE):
            return 'direct'
        raise ValueError('Unsupported media resource; capture an HLS, DASH, or direct video response')

    @staticmethod
    def _yt_dlp_options(output_dir: Path, stem: str, ffmpeg: str, capture: dict, proxy: str, progress_hook, concurrency: int = 8) -> dict:
        headers = dict(capture.get('headers') or {})
        if capture.get('cookie'):
            headers['Cookie'] = str(capture['cookie'])
        options = {
            'format': 'bv*+ba/b',
            'outtmpl': str(output_dir / f'{stem}.%(ext)s'),
            'merge_output_format': 'mp4',
            'hls_prefer_native': True,
            'concurrent_fragment_downloads': max(1, min(16, int(concurrency or 8))),
            'socket_timeout': 30,
            'fragment_retries': 3,
            'retries': 5,
            'file_access_retries': 3,
            'retry_sleep_functions': {'http': retry_delay, 'fragment': retry_delay},
            'noplaylist': True,
            'ffmpeg_location': ffmpeg,
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': True,
        }
        if headers:
            options['http_headers'] = headers
        if proxy:
            options['proxy'] = proxy
        return options

    def create_job(self, request: dict) -> dict:
        capture = request.get('capture')
        if not capture and request.get('captureId'):
            capture = self.captures.get(request['captureId'])
        if not isinstance(capture, dict) or not isinstance(capture.get('url'), str):
            raise ValueError('A captured media URL is required')
        parsed = urlsplit(capture['url'])
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValueError('Only HTTP and HTTPS media URLs are supported')
        kind = self._capture_kind(capture)
        with self.settings_lock:
            settings = self.settings.copy()
        title = str(request.get('filename') or capture.get('title') or 'video')
        job = self._new_job(capture, kind, title, attempt=1, retry_of='')
        with self.lock:
            self.jobs[job['id']] = job
        self._update(job)
        threading.Thread(target=self._run_job, args=(job, request, settings), daemon=True).start()
        return self.public_job(job)

    def _new_job(self, capture: dict, kind: str, title: str, attempt: int, retry_of: str) -> dict:
        timestamp = int(time.time() * 1000)
        return {
            'id': uuid.uuid4().hex,
            'status': 'queued',
            'title': title,
            'url': capture['url'],
            'kind': kind,
            'outputPath': '',
            'progress': 0.0,
            'downloadedFragments': 0,
            'totalFragments': 0,
            'downloadedBytes': 0,
            'totalBytes': 0,
            'speed': '',
            'speedBytesPerSecond': 0,
            'error': '',
            'lastActivityAt': timestamp,
            'stallReason': '',
            'attempt': attempt,
            'retryOf': retry_of,
            'sourceFingerprint': self._source_fingerprint(capture['url']),
            'canRetry': False,
            'createdAt': timestamp,
            'updatedAt': timestamp,
            '_capture': capture,
            '_cancel': threading.Event(),
            '_last_activity_mono': time.monotonic(),
            '_speed_bytes': 0,
            '_speed_at_mono': time.monotonic(),
            '_progress_source': '',
            '_progress_base_bytes': 0,
            '_progress_base_fragments': 0,
            '_progress_base_total_bytes': 0,
            '_progress_base_total_fragments': 0,
            '_progress_phase_bytes': 0,
            '_progress_phase_fragments': 0,
            '_watchdog_expired': False,
            '_internal_abort': False,
            '_last_persist_mono': None,
        }

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', value).strip(' .')
        return name[:160] or 'video'

    @staticmethod
    def _safe_error(error: object) -> str:
        value = str(error)
        value = re.sub(r'https?://[^\s?]+\?[^\s]+', '[remote URL]', value)
        return value[-1200:]

    def _update(self, job: dict, **updates) -> None:
        with self.lock:
            previous_status = job.get('status')
            job.update(updates)
            job['updatedAt'] = int(time.time() * 1000)
            now_mono = time.monotonic()
            status = job.get('status')
            last_persist = job.get('_last_persist_mono')
            should_persist = (
                last_persist is None
                or status != previous_status
                or status in {'completed', 'failed', 'cancelled'}
                or now_mono - float(last_persist) >= PROGRESS_PERSIST_INTERVAL
            )
            if should_persist:
                job['_last_persist_mono'] = now_mono
                snapshot = dict(job)
                self.history.upsert(snapshot)

    def _watchdog(self) -> None:
        while not self._watchdog_stop.wait(5):
            now_mono = time.monotonic()
            with self.lock:
                active_jobs = list(self.jobs.values())
            for job in active_jobs:
                if job.get('status') not in {'queued', 'probing', 'downloading', 'muxing', 'validating'}:
                    continue
                idle = now_mono - float(job.get('_last_activity_mono', now_mono))
                if idle >= STALL_FAILURE_SECONDS and not job.get('_watchdog_expired'):
                    job['_watchdog_expired'] = True
                    job['_cancel'].set()
                    self._update(
                        job,
                        status='failed',
                        canRetry=bool(job.get('_capture')),
                        stallReason=f'连续 {int(STALL_FAILURE_SECONDS)} 秒没有收到下载进度，任务已自动停止',
                        error='下载长时间无进度，已自动停止；可重试',
                        speed='',
                    )
                elif idle >= STALL_WARNING_SECONDS and not job.get('stallReason'):
                    self._update(job, stallReason=f'连续 {int(STALL_WARNING_SECONDS)} 秒没有收到下载进度，可能卡在代理或上游分片')

    def _mark_activity(self, job: dict) -> None:
        now = time.monotonic()
        job['_last_activity_mono'] = now
        job['lastActivityAt'] = int(time.time() * 1000)
        job['stallReason'] = ''

    def _handle_progress_event(self, job: dict, event: dict) -> None:
        with self.lock:
            self._ensure_job_active(job)
            if job.get('status') not in {'queued', 'probing', 'downloading', 'muxing', 'validating'}:
                return
            status = event.get('status')
            previous_bytes = int(job.get('downloadedBytes') or 0)
            previous_fragments = int(job.get('downloadedFragments') or 0)
            previous_total_bytes = int(job.get('totalBytes') or 0)
            previous_total_fragments = int(job.get('totalFragments') or 0)
            info = event.get('info_dict') if isinstance(event.get('info_dict'), dict) else {}
            event_source = str(event.get('filename') or event.get('tmpfilename') or info.get('format_id') or '')
            previous_source = str(job.get('_progress_source') or '')
            if event_source and previous_source and event_source != previous_source:
                job['_progress_base_bytes'] = previous_bytes
                job['_progress_base_fragments'] = previous_fragments
                job['_progress_base_total_bytes'] = previous_total_bytes
                job['_progress_base_total_fragments'] = previous_total_fragments
                job['_progress_phase_bytes'] = 0
                job['_progress_phase_fragments'] = 0
            if event_source:
                job['_progress_source'] = event_source

            raw_bytes = int(event.get('downloaded_bytes') or 0)
            raw_fragments = int(event.get('fragment_index') or 0)
            job['_progress_phase_bytes'] = max(int(job.get('_progress_phase_bytes') or 0), raw_bytes)
            job['_progress_phase_fragments'] = max(int(job.get('_progress_phase_fragments') or 0), raw_fragments)
            downloaded_bytes = max(previous_bytes, int(job.get('_progress_base_bytes') or 0) + int(job['_progress_phase_bytes']))
            downloaded_fragments = max(previous_fragments, int(job.get('_progress_base_fragments') or 0) + int(job['_progress_phase_fragments']))
            event_total_bytes = int(event.get('total_bytes') or event.get('total_bytes_estimate') or 0)
            event_total_fragments = int(event.get('fragment_count') or 0)
            total_bytes = max(previous_total_bytes, int(job.get('_progress_base_total_bytes') or 0) + event_total_bytes)
            total_fragments = max(previous_total_fragments, int(job.get('_progress_base_total_fragments') or 0) + event_total_fragments)
            progressed = downloaded_bytes > previous_bytes or downloaded_fragments > previous_fragments
            updates = {
                'status': 'downloading' if status == 'downloading' else job['status'],
                'downloadedBytes': downloaded_bytes,
                'downloadedFragments': downloaded_fragments,
                'totalBytes': total_bytes,
                'totalFragments': total_fragments,
            }
            if downloaded_bytes and total_bytes:
                updates['progress'] = min(99.0, downloaded_bytes * 100.0 / total_bytes)
            elif downloaded_fragments and total_fragments:
                updates['progress'] = min(95.0, downloaded_fragments * 95.0 / total_fragments)

            event_speed = event.get('speed')
            if isinstance(event_speed, (int, float)) and event_speed > 0:
                updates['speed'] = self.format_speed(int(event_speed))
                updates['speedBytesPerSecond'] = int(event_speed)
            elif downloaded_bytes > previous_bytes:
                now = time.monotonic()
                calculated = self.calculate_speed(
                    int(job.get('_speed_bytes') or 0),
                    downloaded_bytes,
                    now - float(job.get('_speed_at_mono') or now),
                )
                job['_speed_bytes'] = downloaded_bytes
                job['_speed_at_mono'] = now
                updates['speed'] = self.format_speed(calculated) or job.get('speed') or '正在接收数据'
                updates['speedBytesPerSecond'] = calculated
            else:
                updates['speed'] = job.get('speed') or '等待分片响应'

            if progressed or status == 'finished':
                self._mark_activity(job)
                updates['lastActivityAt'] = job['lastActivityAt']
                updates['stallReason'] = ''
            self._update(job, **updates)

    @staticmethod
    def _ensure_job_active(job: dict) -> None:
        if job['_cancel'].is_set():
            raise RuntimeError('Download cancelled')

    def _commit_output(self, source: Path, output_dir: Path, stem: str) -> Path:
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError('Validated output disappeared before it could be saved')
        with self.output_lock:
            target = output_dir / f'{stem}.mp4'
            suffix = 2
            while target.exists():
                target = output_dir / f'{stem} ({suffix}).mp4'
                suffix += 1
            os.replace(source, target)
        return target

    def _process_activity(self, job: dict) -> None:
        with self.lock:
            if job['_cancel'].is_set() or job.get('status') not in {'queued', 'probing', 'downloading', 'muxing', 'validating'}:
                return
            self._mark_activity(job)
            self._update(job, lastActivityAt=job['lastActivityAt'], stallReason='')

    @staticmethod
    def _run_cancellable_process(
        args: list[str],
        timeout: float,
        cancel_event: threading.Event | None = None,
        on_progress=None,
    ) -> subprocess.CompletedProcess:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == 'posix'),
        )
        deadline = time.monotonic() + timeout
        observed_output = 0
        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    HLSGateway._terminate(process)
                    raise RuntimeError('Download cancelled while running a media process')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    HLSGateway._terminate(process)
                    raise RuntimeError(f'Media process timed out after {int(timeout)} seconds')
                try:
                    stdout, stderr = process.communicate(timeout=min(SCHEDULER_POLL_SECONDS, remaining))
                    break
                except subprocess.TimeoutExpired as error:
                    partial_stdout = error.output or b''
                    partial_stderr = error.stderr or b''
                    current_output = len(partial_stdout) + len(partial_stderr)
                    if on_progress and current_output > observed_output:
                        observed_output = current_output
                        on_progress()
        except BaseException:
            HLSGateway._terminate(process)
            raise
        return subprocess.CompletedProcess(
            args=args,
            returncode=process.returncode,
            stdout=stdout.decode('utf-8', 'replace'),
            stderr=stderr.decode('utf-8', 'replace'),
        )

    def retry_job(self, job_id: str) -> dict:
        with self.lock:
            source = self.jobs.get(job_id)
            if not source:
                raise KeyError('Job not found')
            if source.get('status') not in {'failed', 'cancelled'}:
                raise ValueError('Only failed or cancelled jobs can be retried')
            capture = source.get('_capture')
            if not isinstance(capture, dict):
                raise ValueError('The original capture is no longer available; capture the media again')
            kind = source.get('kind') or self._capture_kind(capture)
            title = str(source.get('title') or 'video')
            output_path = str(source.get('outputPath') or '')
            attempt = int(source.get('attempt') or 1) + 1
            with self.settings_lock:
                settings = self.settings.copy()
            request = {
                'capture': capture,
                'filename': title,
                'outputDir': str(Path(output_path).parent) if output_path else settings['outputDir'],
            }
            job = self._new_job(capture, kind, title, attempt=attempt, retry_of=job_id)
            self.jobs[job['id']] = job
        self._update(job)
        threading.Thread(target=self._run_job, args=(job, request, settings), daemon=True).start()
        return self.public_job(job)

    def delete_job(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.get('status') in {'queued', 'probing', 'downloading', 'muxing', 'validating'}:
                return False
        # Persist first so a SQLite error cannot make the UI lose a record that
        # will reappear after the next engine restart.
        self.history.delete(job_id)
        with self.lock:
            self.jobs.pop(job_id, None)
        return True

    def clear_completed(self) -> int:
        with self.lock:
            completed = [job_id for job_id, job in self.jobs.items() if job.get('status') == 'completed']
        deleted = self.history.clear_completed()
        with self.lock:
            for job_id in completed:
                self.jobs.pop(job_id, None)
        return max(deleted, len(completed))

    def _run_job(self, job: dict, request: dict, settings: dict) -> None:
        download_dir: Path | None = None
        try:
            self._update(job, status='probing')
            capture = job['_capture']
            kind = job['kind']
            cancel_event = job['_cancel']
            headers = dict(capture.get('headers') or {})
            if capture.get('cookie'):
                headers['Cookie'] = capture['cookie']
            proxy = str(request['proxy']) if 'proxy' in request else str(settings.get('proxy') or '')
            playlist_url = capture['url']
            if kind == 'hls':
                playlist_url = self.gateway.register(job['id'], capture['url'], headers, proxy, cancel_event)
            output_dir = Path(str(request.get('outputDir') or settings['outputDir'])).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            stem = self._safe_filename(str(request.get('filename') or capture.get('title') or 'video'))
            ffmpeg = str(settings.get('ffmpegPath') or shutil.which('ffmpeg') or '')
            if not ffmpeg:
                raise RuntimeError('ffmpeg was not found. Install ffmpeg or set its path in settings.')
            download_dir = Path(tempfile.mkdtemp(prefix=f'.m3u8-bridge-{job["id"][:8]}-', dir=output_dir))
            png_segments = self.gateway.detect_png_segments(job['id']) if kind == 'hls' else None
            if png_segments:
                staged_path = download_dir / f'{stem}.mp4'
                self._download_png_segments(job, png_segments, staged_path, ffmpeg, int(request.get('concurrency') or settings.get('concurrency') or 8))
                self._ensure_job_active(job)
                self._update(job, status='validating', progress=99.0)
                self._validate(staged_path, ffmpeg, job['_cancel'], lambda: self._process_activity(job))
                self._ensure_job_active(job)
                output_path = self._commit_output(staged_path, output_dir, stem)
                self._update(job, status='completed', progress=100.0, outputPath=str(output_path), speed='')
                return
            try:
                import yt_dlp
            except ImportError:
                yt_dlp = None

            def progress_hook(event: dict) -> None:
                self._handle_progress_event(job, event)

            self._update(job, status='downloading', speed='等待分片响应')
            if yt_dlp is None:
                if kind != 'direct':
                    raise RuntimeError('yt-dlp is unavailable. Run scripts/bootstrap.sh to install the Python engine.')
                output_path = self._download_direct_fallback(job, capture, download_dir, stem, ffmpeg, proxy)
            else:
                options = self._yt_dlp_options(
                    download_dir,
                    stem,
                    ffmpeg,
                    capture,
                    proxy,
                    progress_hook,
                    int(request.get('concurrency') or settings.get('concurrency') or 8),
                )
                try:
                    with yt_dlp.YoutubeDL(options) as downloader:
                        info = downloader.extract_info(playlist_url, download=True)
                        prepared = downloader.prepare_filename(info)
                    output_path = self._find_output(prepared, download_dir, stem)
                except Exception:
                    if kind != 'direct':
                        raise
                    output_path = self._download_direct_fallback(job, capture, download_dir, stem, ffmpeg, proxy)
            self._ensure_job_active(job)
            self._update(job, status='muxing', progress=max(96.0, float(job.get('progress') or 0)))
            output_path = self._normalize_output(
                output_path,
                download_dir,
                stem,
                ffmpeg,
                job['_cancel'],
                lambda: self._process_activity(job),
            )
            self._ensure_job_active(job)
            self._update(job, status='validating', progress=99.0)
            self._validate(output_path, ffmpeg, job['_cancel'], lambda: self._process_activity(job))
            self._ensure_job_active(job)
            output_path = self._commit_output(output_path, output_dir, stem)
            self._update(job, status='completed', progress=100.0, outputPath=str(output_path), speed='', canRetry=False, stallReason='')
        except Exception as error:
            internal_failure = bool(job.get('_watchdog_expired') or job.get('_internal_abort'))
            status = 'failed' if internal_failure else ('cancelled' if job['_cancel'].is_set() else 'failed')
            self._update(
                job,
                status=status,
                canRetry=bool(job.get('_capture')),
                error=job.get('error') if job.get('_watchdog_expired') else ('' if status == 'cancelled' else self._safe_error(error)),
                speed='',
            )
        finally:
            self.gateway.forget(job['id'])
            if download_dir is not None:
                shutil.rmtree(download_dir, ignore_errors=True)

    def _download_direct_fallback(self, job: dict, capture: dict, output_dir: Path, stem: str, ffmpeg: str, proxy: str) -> Path:
        work_dir = Path(tempfile.mkdtemp(prefix=f"m3u8-bridge-{job['id']}-"))
        raw_path = work_dir / 'source.bin'
        try:
            args = [
                'curl', '--location', '--silent', '--show-error', '--fail-with-body',
                '--retry', '5', '--retry-all-errors', '--retry-connrefused',
                '--retry-delay', '1', '--retry-max-time', '180',
                '--connect-timeout', '15', '--speed-time', '30', '--speed-limit', '1024',
                '--output', str(raw_path),
            ]
            if proxy:
                args.extend(['--proxy', proxy])
            headers = dict(capture.get('headers') or {})
            if capture.get('cookie'):
                headers['Cookie'] = str(capture['cookie'])
            for key, value in headers.items():
                if key.lower() in {'cookie', 'authorization', 'user-agent', 'referer', 'origin', 'accept'}:
                    args.extend(['--header', f'{key}: {value}'])
            args.append(str(capture['url']))
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=(os.name == 'posix'),
            )
            cancel_event = job.get('_cancel')
            previous_size = 0
            stderr = b''
            try:
                while True:
                    if cancel_event and cancel_event.is_set():
                        self.gateway._terminate(process)
                        raise RuntimeError('Download cancelled while receiving direct media')
                    try:
                        _stdout, stderr = process.communicate(timeout=SCHEDULER_POLL_SECONDS)
                        break
                    except subprocess.TimeoutExpired:
                        if raw_path.is_file():
                            current_size = raw_path.stat().st_size
                            if current_size > previous_size and cancel_event:
                                now = time.monotonic()
                                speed = self.calculate_speed(
                                    int(job.get('_speed_bytes') or 0),
                                    current_size,
                                    now - float(job.get('_speed_at_mono') or now),
                                )
                                job['_speed_bytes'] = current_size
                                job['_speed_at_mono'] = now
                                previous_size = current_size
                                self._mark_activity(job)
                                self._update(
                                    job,
                                    downloadedBytes=current_size,
                                    speed=self.format_speed(speed) or job.get('speed') or '正在接收数据',
                                    lastActivityAt=job['lastActivityAt'],
                                    stallReason='',
                                )
            except BaseException:
                self.gateway._terminate(process)
                raise
            if process.returncode or not raw_path.is_file() or raw_path.stat().st_size == 0:
                detail = stderr.decode('utf-8', 'replace')[-800:]
                raise RuntimeError(f'Direct media download failed: {detail}')
            if cancel_event and cancel_event.is_set():
                raise RuntimeError('Download cancelled while receiving direct media')
            if cancel_event:
                current_size = raw_path.stat().st_size
                self._mark_activity(job)
                self._update(job, downloadedBytes=current_size, lastActivityAt=job['lastActivityAt'], stallReason='')
            output_path = output_dir / f'{stem}.mp4'
            self._encode_mp4(
                raw_path,
                output_path,
                ffmpeg,
                job.get('_cancel'),
                (lambda: self._process_activity(job)) if job.get('_cancel') else None,
            )
            return output_path
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def _probe_streams(path: Path) -> list[dict]:
        ffprobe = os.environ.get('M3U8_BRIDGE_FFPROBE') or shutil.which('ffprobe')
        if not ffprobe:
            raise RuntimeError('ffprobe was not found; cannot inspect the downloaded video')
        result = subprocess.run([
            ffprobe, '-v', 'error', '-show_entries',
            'stream=codec_type,codec_name,codec_tag_string,pix_fmt',
            '-of', 'json', str(path),
        ], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'ffprobe rejected the output: {result.stderr[-500:]}')
        return json.loads(result.stdout).get('streams', [])

    @classmethod
    def _normalize_output(
        cls,
        source: Path,
        output_dir: Path,
        stem: str,
        ffmpeg: str,
        cancel_event: threading.Event | None = None,
        on_progress=None,
    ) -> Path:
        streams = cls._probe_streams(source)
        video = next((stream for stream in streams if stream.get('codec_type') == 'video'), None)
        audio = next((stream for stream in streams if stream.get('codec_type') == 'audio'), None)
        pixel_format = video.get('pix_fmt') if video else None
        quicklook_pixels = {None, 'yuv420p', 'yuvj420p'}
        video_compatible = bool(video) and (
            (video.get('codec_name') == 'h264' and pixel_format in quicklook_pixels)
            or (
                video.get('codec_name') == 'hevc'
                and video.get('codec_tag_string') == 'hvc1'
                and pixel_format in quicklook_pixels
            )
        )
        compatible = source.suffix.lower() == '.mp4' and video_compatible and (not audio or audio.get('codec_name') in {'aac', 'alac', 'mp3'})
        target = output_dir / f'{stem}.mp4'
        if compatible:
            if source != target:
                os.replace(source, target)
            return target
        encoded = target if source != target else output_dir / f'.{stem}.normalized.mp4'
        cls._encode_mp4(source, encoded, ffmpeg, cancel_event, on_progress)
        if encoded != target:
            os.replace(encoded, target)
        if source != target and source.exists():
            source.unlink()
        return target

    @classmethod
    def _encode_mp4(
        cls,
        source: Path,
        target: Path,
        ffmpeg: str,
        cancel_event: threading.Event | None = None,
        on_progress=None,
    ) -> None:
        args = [
            ffmpeg, '-hide_banner', '-v', 'error', '-xerror', '-y', '-progress', 'pipe:1', '-nostats', '-i', str(source),
            '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'medium', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(target),
        ]
        result = cls._run_cancellable_process(
            args,
            timeout=900,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
        if result.returncode or not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f'Could not normalize video to MP4: {result.stderr[-800:]}')

    def _download_png_segments(self, job: dict, segments: list[tuple[str, float]], output_path: Path, ffmpeg: str, concurrency: int) -> None:
        work_dir = Path(tempfile.mkdtemp(prefix=f"m3u8-bridge-{job['id']}-"))
        concurrency = max(1, min(16, concurrency))
        completed = 0
        downloaded_bytes = 0
        clean_files: list[Path | None] = [None] * len(segments)
        segment_kinds: list[str | None] = [None] * len(segments)
        durations: list[float] = [0.0] * len(segments)
        self._update(job, status='downloading', totalFragments=len(segments), downloadedFragments=0)

        def fetch_segment(item: tuple[int, tuple[str, float]]) -> tuple[int, Path, str, float, int]:
            index, (url, duration) = item
            last_error: Exception | None = None
            for attempt in range(1, 4):
                if job['_cancel'].is_set():
                    raise RuntimeError('Download cancelled')
                try:
                    data = self.gateway.fetch_remote(job['id'], url)
                    self._ensure_job_active(job)
                    raw_path = work_dir / f'segment-{index:06d}.bin'
                    transport = self._extract_png_wrapped_mpegts(data)
                    if transport is not None:
                        clean_path = work_dir / f'segment-{index:06d}.ts'
                        clean_path.write_bytes(transport)
                        segment_kind = 'mpegts'
                    else:
                        clean_path = work_dir / f'segment-{index:06d}.png'
                        self._convert_image_segment(data, raw_path, clean_path, ffmpeg, index, job['_cancel'])
                        segment_kind = 'image'
                    return index, clean_path, segment_kind, duration, len(data)
                except Exception as error:
                    last_error = error
                    if attempt < 3:
                        if job['_cancel'].wait(retry_delay(attempt)):
                            raise RuntimeError('Download cancelled') from error
            raise RuntimeError(f'Could not normalize PNG segment {index + 1}: {last_error}') from last_error

        pool = ThreadPoolExecutor(max_workers=concurrency)
        inflight = {}
        segment_iter = iter(enumerate(segments))
        cleanup_deferred = False

        def submit_next() -> bool:
            try:
                item = next(segment_iter)
            except StopIteration:
                return False
            inflight[pool.submit(fetch_segment, item)] = item[0]
            return True

        try:
            for _ in range(min(concurrency, len(segments))):
                submit_next()
            while inflight:
                done, _ = wait(inflight, timeout=SCHEDULER_POLL_SECONDS, return_when=FIRST_COMPLETED)
                if not done:
                    self._ensure_job_active(job)
                    idle = time.monotonic() - float(job.get('_last_activity_mono', time.monotonic()))
                    if idle >= STALL_FAILURE_SECONDS:
                        job['_watchdog_expired'] = True
                        job['_cancel'].set()
                        self._update(
                            job,
                            status='failed',
                            canRetry=bool(job.get('_capture')),
                            stallReason=f'连续 {int(STALL_FAILURE_SECONDS)} 秒没有收到分片进度，任务已自动停止',
                            error='PNG 分片下载长时间无进度，已自动停止；可重试',
                            speed='',
                        )
                        raise RuntimeError('PNG segment downloads made no progress before the timeout')
                    continue
                for future in done:
                    inflight.pop(future, None)
                    index, clean_path, segment_kind, duration, byte_count = future.result()
                    clean_files[index] = clean_path
                    segment_kinds[index] = segment_kind
                    durations[index] = duration
                    completed += 1
                    downloaded_bytes += byte_count
                    self._ensure_job_active(job)
                    now = time.monotonic()
                    speed = self.calculate_speed(
                        int(job.get('_speed_bytes') or 0),
                        downloaded_bytes,
                        now - float(job.get('_speed_at_mono') or now),
                    )
                    job['_speed_bytes'] = downloaded_bytes
                    job['_speed_at_mono'] = now
                    self._mark_activity(job)
                    self._update(
                        job,
                        downloadedFragments=completed,
                        downloadedBytes=downloaded_bytes,
                        speed=self.format_speed(speed) or job.get('speed') or '正在接收分片',
                        progress=min(94.0, completed * 94.0 / len(segments)),
                    )
                    if job['_cancel'].is_set():
                        raise RuntimeError('Download cancelled')
                    submit_next()
            pool.shutdown(wait=True)

            if any(path is None for path in clean_files):
                raise RuntimeError('Some image segments were not downloaded')
            kinds = set(segment_kinds)
            if len(kinds) != 1:
                raise RuntimeError('Image HLS contains mixed image and MPEG-TS segments')
            self._update(job, status='muxing', progress=96.0)
            if kinds == {'mpegts'}:
                transport_path = work_dir / 'segments.ts'
                with transport_path.open('wb') as target:
                    for segment_path in clean_files:
                        with segment_path.open('rb') as source:
                            shutil.copyfileobj(source, target)
                        segment_path.unlink()
                        self._process_activity(job)
                args = [
                    ffmpeg, '-hide_banner', '-v', 'error', '-xerror', '-y', '-progress', 'pipe:1', '-nostats',
                    '-i', str(transport_path), '-map', '0:v:0', '-map', '0:a?', '-c', 'copy',
                    '-movflags', '+faststart', str(output_path),
                ]
            else:
                concat_path = work_dir / 'segments.ffconcat'
                with concat_path.open('w') as manifest:
                    manifest.write('ffconcat version 1.0\n')
                    for image_path, duration in zip(clean_files, durations):
                        manifest.write(f"file '{image_path.as_posix()}'\n")
                        manifest.write(f'duration {max(0.04, duration):.6f}\n')
                    manifest.write(f"file '{clean_files[-1].as_posix()}'\n")
                args = [
                    ffmpeg, '-hide_banner', '-v', 'error', '-xerror', '-y', '-progress', 'pipe:1', '-nostats',
                    '-f', 'concat', '-safe', '0', '-i', str(concat_path), '-vsync', 'vfr', '-an',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output_path),
                ]
            result = self._run_cancellable_process(
                args,
                timeout=max(120, len(segments) * 2),
                cancel_event=job['_cancel'],
                on_progress=lambda: self._process_activity(job),
            )
            if result.returncode:
                raise RuntimeError(f'Image HLS encoding failed: {result.stderr[-800:]}')
        except BaseException:
            if not job['_cancel'].is_set():
                job['_internal_abort'] = True
            job['_cancel'].set()
            for future in inflight:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            if any(not future.done() for future in inflight):
                cleanup_deferred = True
                threading.Thread(
                    target=self._finish_png_cleanup,
                    args=(pool, work_dir),
                    name=f'png-cleanup-{job["id"][:8]}',
                    daemon=True,
                ).start()
            raise
        finally:
            if not cleanup_deferred:
                shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def _finish_png_cleanup(pool: ThreadPoolExecutor, work_dir: Path) -> None:
        pool.shutdown(wait=True, cancel_futures=True)
        shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def _image_format(data: bytes) -> str | None:
        signatures = (
            (b'\x89PNG\r\n\x1a\n', 'PNG'),
            (b'\xff\xd8\xff', 'JPEG'),
            (b'GIF87a', 'GIF'),
            (b'GIF89a', 'GIF'),
            (b'RIFF', 'WebP'),
        )
        for signature, name in signatures:
            if data.startswith(signature):
                if name != 'WebP' or data[8:12] == b'WEBP':
                    return name
        return None

    @staticmethod
    def _extract_png_wrapped_mpegts(data: bytes) -> bytes | None:
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            return None
        position = 8
        png_end = None
        while position + 12 <= len(data):
            chunk_size = int.from_bytes(data[position:position + 4], 'big')
            chunk_type = data[position + 4:position + 8]
            next_position = position + 12 + chunk_size
            if next_position > len(data):
                return None
            position = next_position
            if chunk_type == b'IEND':
                png_end = position
                break
        if png_end is None:
            return None

        search_end = min(len(data), png_end + 65536)
        candidate = data.find(b'\x47', png_end, search_end)
        while candidate >= 0:
            payload_size = len(data) - candidate
            packet_count, remainder = divmod(payload_size, 188)
            if remainder == 0 and packet_count >= 5:
                checks = min(packet_count, 12)
                if all(data[candidate + packet * 188] == 0x47 for packet in range(checks)):
                    return data[candidate:]
            candidate = data.find(b'\x47', candidate + 1, search_end)
        return None

    @classmethod
    def _convert_image_segment(
        cls,
        data: bytes,
        raw_path: Path,
        clean_path: Path,
        ffmpeg: str,
        index: int,
        cancel_event: threading.Event | None = None,
    ) -> None:
        image_format = cls._image_format(data)
        if image_format is None:
            raise RuntimeError('upstream response is not a supported image; it may be an HTML error page or an expired segment')
        raw_path.write_bytes(data)
        converted = cls._run_cancellable_process([
            ffmpeg, '-hide_banner', '-v', 'error', '-xerror', '-y', '-i', str(raw_path),
            '-frames:v', '1', '-f', 'image2', str(clean_path),
        ], timeout=30, cancel_event=cancel_event)
        if converted.returncode or not clean_path.is_file() or clean_path.stat().st_size == 0:
            detail = converted.stderr[-400:] if converted.stderr else 'no decoder output'
            raise RuntimeError(f'{image_format} decode failed: {detail}')

    @staticmethod
    def _find_output(prepared: str, output_dir: Path, stem: str) -> Path:
        candidates = [Path(prepared), Path(prepared).with_suffix('.mp4')]
        candidates.extend(sorted(output_dir.glob(f'{stem}.*'), key=lambda path: path.stat().st_mtime, reverse=True))
        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        raise RuntimeError('yt-dlp finished without creating an output file')

    @classmethod
    def _validate(
        cls,
        path: Path,
        ffmpeg: str,
        cancel_event: threading.Event | None = None,
        on_progress=None,
    ) -> None:
        ffprobe = os.environ.get('M3U8_BRIDGE_FFPROBE') or shutil.which('ffprobe')
        if not ffprobe:
            raise RuntimeError('ffprobe was not found; cannot validate the downloaded video')
        probe = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
        if probe.returncode:
            raise RuntimeError(f'ffprobe rejected the output: {probe.stderr[-500:]}')
        data = json.loads(probe.stdout)
        if not any(stream.get('codec_type') == 'video' for stream in data.get('streams', [])):
            raise RuntimeError('The output contains no video stream')
        duration = float((data.get('format') or {}).get('duration') or 0)
        if duration <= 0:
            raise RuntimeError('The output has no valid duration')
        packet_scan = cls._run_cancellable_process(
            [
                ffmpeg, '-v', 'error', '-xerror', '-progress', 'pipe:1', '-nostats',
                '-i', str(path), '-map', '0:v:0', '-map', '0:a?', '-c', 'copy', '-f', 'null', '-',
            ],
            timeout=900,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
        if packet_scan.returncode:
            raise RuntimeError(f'ffmpeg full-file scan failed: {packet_scan.stderr[-500:]}')
        decode = cls._run_cancellable_process(
            [ffmpeg, '-v', 'error', '-xerror', '-progress', 'pipe:1', '-nostats', '-i', str(path), '-t', '5', '-f', 'null', '-'],
            timeout=45,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
        if decode.returncode:
            raise RuntimeError(f'ffmpeg decode check failed: {decode.stderr[-500:]}')
        if duration > 10:
            tail_decode = cls._run_cancellable_process(
                [
                    ffmpeg, '-v', 'error', '-xerror', '-progress', 'pipe:1', '-nostats',
                    '-sseof', '-5', '-i', str(path), '-t', '5', '-f', 'null', '-',
                ],
                timeout=45,
                cancel_event=cancel_event,
                on_progress=on_progress,
            )
            if tail_decode.returncode:
                raise RuntimeError(f'ffmpeg tail decode check failed: {tail_decode.stderr[-500:]}')


# Keep imports side-effect free for unit tests; the long-lived server enables
# recovery and the watchdog in main() once it owns the process.
ENGINE: Engine | None = None


def current_engine() -> Engine:
    if ENGINE is None:
        raise RuntimeError('The engine server has not been started')
    return ENGINE


class Handler(BaseHTTPRequestHandler):
    server_version = 'm3u8-bridge/' + __version__

    def log_message(self, format: str, *args) -> None:
        message = format % args
        message = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[redacted]', message)
        print(f'[http] {message}', flush=True)

    def _cors(self) -> None:
        origin = self.headers.get('Origin', '')
        if origin in {'http://localhost:5173', 'http://127.0.0.1:5173', 'tauri://localhost', 'http://tauri.localhost'} or origin.startswith('chrome-extension://'):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, Range')
            self.send_header('Access-Control-Allow-Methods', 'DELETE, GET, POST, OPTIONS')

    def _send(self, status: int, payload: bytes, content_type: str = 'application/json; charset=utf-8', extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, value: object) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode())

    def _body(self) -> dict:
        length = min(int(self.headers.get('Content-Length', 0)), 2_000_000)
        return json.loads(self.rfile.read(length) or b'{}')

    def _authorized(self) -> bool:
        return self.headers.get('Authorization') == f'Bearer {current_engine().token}'

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == '/healthz':
            self._json(200, engine_health())
            return
        if path == '/api/session':
            self._json(200, {'token': current_engine().token})
            return
        if path.startswith('/hls/'):
            try:
                data, content_type, status, headers = current_engine().gateway.handle(path, self.headers.get('Range'))
                self._send(status, data, content_type, headers)
            except KeyError as error:
                self._json(404, {'error': str(error)})
            except Exception as error:
                self._json(502, {'error': current_engine()._safe_error(error)})
            return
        if not self._authorized():
            self._json(401, {'error': 'Unauthorized'})
            return
        if path == '/api/jobs':
            with current_engine().lock:
                jobs = [current_engine().public_job(job) for job in sorted(current_engine().jobs.values(), key=lambda item: item['createdAt'], reverse=True)]
            self._json(200, jobs)
        elif path.startswith('/api/jobs/'):
            job_id = path.rsplit('/', 1)[-1]
            with current_engine().lock:
                job = current_engine().jobs.get(job_id)
            self._json(200 if job else 404, current_engine().public_job(job) if job else {'error': 'Job not found'})
        elif path == '/api/settings':
            with current_engine().settings_lock:
                self._json(200, current_engine().settings.copy())
        else:
            self._json(404, {'error': 'Not found'})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if not self._authorized():
            self._json(401, {'error': 'Unauthorized'})
            return
        try:
            payload = self._body()
            if path == '/api/captures':
                capture_id = uuid.uuid4().hex
                payload['id'] = capture_id
                current_engine().captures[capture_id] = payload
                self._json(201, {'id': capture_id})
            elif path == '/api/jobs':
                job = current_engine().create_job(payload)
                self._json(202, job)
            elif path.startswith('/api/jobs/') and path.endswith('/cancel'):
                job_id = path.split('/')[-2]
                with current_engine().lock:
                    job = current_engine().jobs.get(job_id)
                    if job and job['status'] not in ('completed', 'failed', 'cancelled'):
                        job['_cancel'].set()
                self._json(200 if job else 404, current_engine().public_job(job) if job else {'error': 'Job not found'})
            elif path.startswith('/api/jobs/') and path.endswith('/retry'):
                job_id = path.split('/')[-2]
                job = current_engine().retry_job(job_id)
                self._json(202, job)
            elif path == '/api/jobs/clear-completed':
                self._json(200, {'deleted': current_engine().clear_completed()})
            elif path == '/api/app/activate':
                self._json(200, {'activated': activate_desktop()})
            elif path == '/api/settings':
                allowed = {'outputDir', 'proxy', 'concurrency', 'ffmpegPath', 'pythonPath'}
                with current_engine().settings_lock:
                    current_engine().settings.update({key: value for key, value in payload.items() if key in allowed})
                    current_engine().settings['concurrency'] = max(1, min(16, int(current_engine().settings.get('concurrency', 8))))
                    settings_path().parent.mkdir(parents=True, exist_ok=True)
                    settings_path().write_text(json.dumps(current_engine().settings, indent=2))
                    self._json(200, current_engine().settings.copy())
            else:
                self._json(404, {'error': 'Not found'})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._json(400, {'error': str(error)})
        except Exception as error:
            self._json(500, {'error': current_engine()._safe_error(error)})

    def do_DELETE(self) -> None:
        path = urlsplit(self.path).path
        if not self._authorized():
            self._json(401, {'error': 'Unauthorized'})
            return
        if not path.startswith('/api/jobs/'):
            self._json(404, {'error': 'Not found'})
            return
        job_id = path.rsplit('/', 1)[-1]
        deleted = current_engine().delete_job(job_id)
        self._json(200 if deleted else 409, {'deleted': deleted})


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    port = int(os.environ.get('M3U8_BRIDGE_PORT', '8765'))
    global ENGINE
    ENGINE = Engine(recover=True)
    current_engine().gateway.base_url = f'http://127.0.0.1:{port}'
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    if os.environ.get('M3U8_BRIDGE_DESKTOP_PID'):
        threading.Thread(
            target=monitor_desktop_parent,
            args=(server.shutdown,),
            name='desktop-parent-watch',
            daemon=True,
        ).start()
    print(f'm3u8-bridge engine listening on 127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
