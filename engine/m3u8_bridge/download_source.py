"""Resolve known single-track captures to a complete, site-extracted video."""

from urllib.parse import parse_qs, urlsplit
import re


YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}
YOUTUBE_SHORT_HOST = 'youtu.be'
YOUTUBE_CANONICAL_HOST = 'www.youtube.com'
YOUTUBE_MEDIA_SUFFIX = '.googlevideo.com'


def youtube_page_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return None
        host = (parsed.hostname or '').lower()
        if host == YOUTUBE_SHORT_HOST:
            video_id = parsed.path.strip('/')
        elif host in YOUTUBE_HOSTS:
            if parsed.path == '/watch':
                video_id = (parse_qs(parsed.query).get('v') or [''])[0]
            elif re.fullmatch(r'/(?:shorts|embed|live)/[^/]+/?', parsed.path):
                video_id = parsed.path.strip('/').split('/')[-1]
            else:
                return None
        else:
            return None
        if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            return f'https://{YOUTUBE_CANONICAL_HOST}/watch?v={video_id}'
    except ValueError:
        pass
    return None


def download_source(capture: dict) -> tuple[str, dict, bool]:
    url = str(capture.get('url') or '')
    page = youtube_page_url(url)
    host = (urlsplit(url).hostname or '').lower()
    is_media = host == YOUTUBE_MEDIA_SUFFIX[1:] or host.endswith(YOUTUBE_MEDIA_SUFFIX)
    if is_media:
        page = youtube_page_url(str(capture.get('pageUrl') or ''))
        if not page:
            raise ValueError('YouTube media capture requires its original page URL; refresh the video page and capture again')
    if not page:
        return url, capture, False

    # CDN requests can carry byte ranges and CDN-only credentials. Never forward
    # those to a different origin or reuse them for a complete site download.
    same_host = host == YOUTUBE_CANONICAL_HOST
    allowed = {'user-agent', 'accept-language'}
    if same_host:
        allowed.update({'cookie', 'authorization'})
    headers = {key: value for key, value in (capture.get('headers') or {}).items() if key.lower() in allowed}
    headers['Referer'] = page
    context = {**capture, 'url': page, 'kind': 'direct', 'headers': headers}
    if not same_host:
        context.pop('cookie', None)
    return page, context, True
