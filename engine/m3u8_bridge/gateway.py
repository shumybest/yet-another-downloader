from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass, field


@dataclass
class StreamContext:
    job_id: str
    url: str
    headers: dict[str, str]
    proxy: str
    cancel_event: threading.Event | None = None
    resources: dict[str, str] = field(default_factory=dict)


class HLSGateway:
    """Loopback HLS relay that keeps browser credentials in process memory."""

    def __init__(self, base_url: str = 'http://127.0.0.1:8765') -> None:
        self.base_url = base_url.rstrip('/')
        self.streams: dict[str, StreamContext] = {}
        self.lock = threading.RLock()

    def register(self, job_id: str, url: str, headers: dict[str, str], proxy: str, cancel_event: threading.Event | None = None) -> str:
        with self.lock:
            self.streams[job_id] = StreamContext(job_id=job_id, url=url, headers=headers, proxy=proxy, cancel_event=cancel_event)
        return f'{self.base_url}/hls/{job_id}/playlist.m3u8'

    def forget(self, job_id: str) -> None:
        with self.lock:
            self.streams.pop(job_id, None)

    def detect_png_segments(self, job_id: str) -> list[tuple[str, float]] | None:
        with self.lock:
            context = self.streams[job_id]
        playlist_url = context.url
        for _ in range(8):
            payload, _, _, _ = self._fetch(playlist_url, context)
            text = payload.decode('utf-8-sig')
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not any(line.startswith('#EXTINF:') for line in lines):
                variants: list[tuple[int, str]] = []
                for index, line in enumerate(lines):
                    if line.startswith('#EXT-X-STREAM-INF:'):
                        next_line = next((candidate for candidate in lines[index + 1:] if not candidate.startswith('#')), None)
                        if next_line:
                            bandwidth_match = re.search(r'BANDWIDTH=(\d+)', line)
                            variants.append((int(bandwidth_match.group(1)) if bandwidth_match else 0, next_line))
                if not variants:
                    return None
                playlist_url = urllib.parse.urljoin(playlist_url, max(variants)[1])
                playlist_url = self._repair_googleusercontent(playlist_url)
                continue

            segments: list[tuple[str, float]] = []
            pending_duration = 0.0
            for line in lines:
                if line.startswith('#EXTINF:'):
                    try:
                        pending_duration = float(line.split(':', 1)[1].split(',', 1)[0])
                    except ValueError:
                        pending_duration = 0.0
                elif not line.startswith('#'):
                    segments.append((self._repair_googleusercontent(urllib.parse.urljoin(playlist_url, line)), pending_duration))
                    pending_duration = 0.0
            if not segments:
                return None
            first, _, _, _ = self._fetch(segments[0][0], context)
            return segments if first.startswith(b'\x89PNG\r\n\x1a\n') else None
        return None

    def fetch_remote(self, job_id: str, url: str) -> bytes:
        with self.lock:
            context = self.streams[job_id]
        payload, _, _, _ = self._fetch(url, context)
        return payload

    def handle(self, path: str, range_header: str | None = None) -> tuple[bytes, str, int, dict[str, str]]:
        parts = path.strip('/').split('/')
        if len(parts) < 3 or parts[0] != 'hls':
            raise ValueError('Invalid HLS gateway path')
        job_id = parts[1]
        with self.lock:
            context = self.streams.get(job_id)
        if not context:
            raise KeyError('HLS session expired')
        if len(parts) == 3 and parts[2] == 'playlist.m3u8':
            return self._playlist(context.url, context, range_header)
        if len(parts) == 4 and parts[2] == 'resource':
            resource_id = parts[3].rsplit('.', 1)[0]
            remote_url = context.resources.get(resource_id)
            if not remote_url:
                raise KeyError('HLS resource expired')
            payload, content_type, status, response_headers = self._fetch(remote_url, context, range_header)
            if payload.lstrip().startswith(b'#EXTM3U'):
                return self._rewrite(payload.decode('utf-8-sig'), remote_url, context).encode(), 'application/vnd.apple.mpegurl', 200, {}
            return payload, content_type, status, response_headers
        raise ValueError('Unknown HLS gateway route')

    def _rewrite(self, body: str, playlist_url: str, context: StreamContext) -> str:
        output: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                output.append(line)
                continue
            if stripped.startswith('#'):
                output.append(re.sub(r'URI="([^"]+)"', lambda match: f'URI="{self._local_url(match.group(1), playlist_url, context)}"', line))
            else:
                output.append(self._local_url(stripped, playlist_url, context))
        return '\n'.join(output) + '\n'

    def _local_url(self, value: str, playlist_url: str, context: StreamContext) -> str:
        absolute = urllib.parse.urljoin(playlist_url, value)
        absolute = self._repair_googleusercontent(absolute)
        resource_id = hashlib.sha256(absolute.encode()).hexdigest()[:24]
        context.resources[resource_id] = absolute
        suffix = '.m3u8' if urllib.parse.urlparse(absolute).path.lower().endswith('.m3u8') else '.ts'
        return f'{self.base_url}/hls/{self._job_id(context)}/resource/{resource_id}{suffix}'

    def _job_id(self, context: StreamContext) -> str:
        return context.job_id

    @staticmethod
    def _repair_googleusercontent(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        match = re.fullmatch(r'/d/([^/=]+)=d?', parsed.path)
        if parsed.hostname == 'lh3.googleusercontent.com' and match:
            query = urllib.parse.urlencode({'id': match.group(1), 'export': 'download', 'confirm': 't'})
            return f'https://drive.usercontent.google.com/download?{query}'
        return url

    def _fetch(self, url: str, context: StreamContext, range_header: str | None = None) -> tuple[bytes, str, int, dict[str, str]]:
        args = [
            'curl', '--location', '--silent', '--show-error', '--fail-with-body',
            '--retry', '1', '--retry-all-errors', '--retry-connrefused', '--retry-max-time', '30',
            '--connect-timeout', '15', '--max-time', '30',
            '-w', '\n__MB_STATUS__%{http_code}',
        ]
        if context.proxy:
            args.extend(['--proxy', context.proxy])
        for key, value in context.headers.items():
            if key.lower() in {'cookie', 'authorization', 'user-agent', 'referer', 'origin', 'accept'}:
                args.extend(['--header', f'{key}: {value}'])
        if range_header:
            args.extend(['--header', f'Range: {range_header}'])
        args.append(url)
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == 'posix'),
        )
        deadline = time.monotonic() + 35
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=min(0.5, max(0.05, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if context.cancel_event and context.cancel_event.is_set():
                        self._terminate(process)
                        raise RuntimeError('Download cancelled while waiting for upstream segment')
                    if time.monotonic() >= deadline:
                        self._terminate(process)
                        raise RuntimeError('Upstream segment request timed out after 35 seconds')
        except Exception:
            if process.poll() is None:
                self._terminate(process)
            raise
        result = type('Completed', (), {'returncode': process.returncode, 'stdout': stdout, 'stderr': stderr})()
        marker = b'\n__MB_STATUS__'
        body, separator, status = result.stdout.rpartition(marker)
        if result.returncode or not separator or not status.isdigit() or int(status) >= 400:
            detail = result.stderr.decode('utf-8', 'replace')[-600:]
            raise RuntimeError(f'Upstream request failed ({status.decode() if status else result.returncode}): {detail}')
        content_type = 'application/octet-stream'
        path = urllib.parse.urlparse(url).path.lower()
        if path.endswith('.m3u8'):
            content_type = 'application/vnd.apple.mpegurl'
        elif path.endswith(('.ts', '.m4s', '.mp4')):
            content_type = 'video/mp2t'
        forwarded: dict[str, str] = {}
        if int(status) == 206 and range_header:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', range_header.strip())
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else start + len(body) - 1
                forwarded = {'Content-Range': f'bytes {start}-{end}/*', 'Accept-Ranges': 'bytes'}
        return body, content_type, int(status), forwarded

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            for stream_name in ('stdout', 'stderr', 'stdin'):
                stream = getattr(process, stream_name, None)
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            return
        try:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == 'posix':
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=2)
            except OSError:
                pass
            except subprocess.TimeoutExpired:
                pass
        finally:
            for stream_name in ('stdout', 'stderr', 'stdin'):
                stream = getattr(process, stream_name, None)
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def _playlist(self, url: str, context: StreamContext, range_header: str | None) -> tuple[bytes, str, int, dict[str, str]]:
        payload, _, _, _ = self._fetch(url, context, range_header)
        return self._rewrite(payload.decode('utf-8-sig'), url, context).encode(), 'application/vnd.apple.mpegurl', 200, {}
