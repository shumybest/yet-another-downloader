import type { MediaKind } from '@m3u8-bridge/protocol';

const DIRECT_EXTENSIONS = /\.(?:mp4|m4v|mov|webm|mkv|flv|f4v|mpeg|mpg|ogv|3gp)(?:$|[?#])/i;
const SEGMENT_EXTENSIONS = /\.(?:ts|m4s|cmfv|cmfa|aac|vtt|key)(?:$|[?#])/i;
const SEGMENT_MARKERS = /(?:^|[\/_-])(?:segment|chunk|frag|fragment|init)(?:[\/_?=-]|$)/i;
const HLS_TYPES = /(?:mpegurl|vnd\.apple\.mpegurl)/i;
const DASH_TYPES = /(?:dash\+xml)/i;
const VIDEO_TYPES = /^video\//i;

export interface MediaDetectionContext {
  resourceType?: string;
  contentDisposition?: string;
}

function normalizedContentType(contentType: string): string {
  return contentType.split(';', 1)[0].trim().toLowerCase();
}

function isSegment(url: string, contentType: string): boolean {
  const type = normalizedContentType(contentType);
  return SEGMENT_EXTENSIONS.test(url) || SEGMENT_MARKERS.test(url) || type === 'video/mp2t' || type === 'video/iso.segment' || type === 'audio/aac';
}

function decodeFilename(value: string): string {
  const unquoted = value.trim().replace(/^['"]|['"]$/g, '');
  try {
    return decodeURIComponent(unquoted);
  } catch {
    return unquoted;
  }
}

function dispositionFilename(contentDisposition: string | undefined): string | undefined {
  if (!contentDisposition) return undefined;
  const encoded = contentDisposition.match(/(?:^|;)\s*filename\*\s*=\s*(?:UTF-8''|''|)([^;]+)/i)?.[1];
  if (encoded) return decodeFilename(encoded);
  const plain = contentDisposition.match(/(?:^|;)\s*filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
  return plain ? decodeFilename(plain[1] ?? plain[2]) : undefined;
}

function hasDirectExtension(value: string | undefined): boolean {
  return Boolean(value && DIRECT_EXTENSIONS.test(value));
}

export function contentLengthFromResponse(contentLength?: string | number, contentRange?: string): number | undefined {
  const length = Number(contentLength);
  if (Number.isFinite(length) && length > 0) return length;
  const total = contentRange?.match(/\bbytes\s+\d+-\d+\/(\d+)\b/i)?.[1];
  const rangeLength = Number(total);
  return Number.isFinite(rangeLength) && rangeLength > 0 ? rangeLength : undefined;
}

export function classifyMedia(url: string, contentType = '', context: MediaDetectionContext = {}): MediaKind | null {
  const type = normalizedContentType(contentType);
  if (/\.m3u8(?:$|[?#])/i.test(url) || HLS_TYPES.test(type)) return 'hls';
  if (/\.mpd(?:$|[?#])/i.test(url) || DASH_TYPES.test(type)) return 'dash';
  if (isSegment(url, type)) return null;
  if (VIDEO_TYPES.test(type) || hasDirectExtension(url) || hasDirectExtension(dispositionFilename(context.contentDisposition))) return 'direct';
  if (context.resourceType?.toLowerCase() === 'media') return 'direct';
  return null;
}

export function isMediaUrl(url: string, contentType = '', context?: MediaDetectionContext): boolean {
  return classifyMedia(url, contentType, context) !== null;
}

export function isHlsUrl(url: string, contentType = '', context?: MediaDetectionContext): boolean {
  return classifyMedia(url, contentType, context) === 'hls';
}

export function normalizeHeaders(headers: chrome.webRequest.HttpHeader[] | undefined): Record<string, string> {
  const result: Record<string, string> = {};
  for (const header of headers ?? []) {
    if (!header.name || header.value == null) continue;
    const key = header.name.toLowerCase();
    if (key === 'cookie' || key === 'authorization' || key === 'user-agent' || key === 'referer' || key === 'origin') {
      result[header.name] = header.value;
    }
  }
  return result;
}

export function fingerprint(url: string, tabId?: number, kind?: MediaKind): string {
  return kind ? `${tabId ?? 0}:${kind}:${url}` : `${tabId ?? 0}:${url}`;
}

export function titleFromUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const name = decodeURIComponent(parsed.pathname.split('/').filter(Boolean).pop() ?? 'video');
    return name.replace(/\.(?:m3u8|mpd|mp4|m4v|mov|webm|mkv|flv|f4v|mpeg|mpg|ogv|3gp)$/i, '') || 'video';
  } catch {
    return 'video';
  }
}
