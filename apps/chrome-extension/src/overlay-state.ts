export interface OverlayCapture {
  id: string;
  url: string;
  title?: string;
  kind?: 'hls' | 'dash' | 'direct';
  contentType?: string;
  contentLength?: number;
  mediaInfo?: MediaInfo;
}

export interface MediaInfo {
  width?: number;
  height?: number;
  duration?: number;
  bitrate?: number;
  videoCodec?: string;
  audioCodec?: string;
  renditions?: MediaRendition[];
}

export interface MediaRendition {
  id: string;
  url?: string;
  width?: number;
  height?: number;
  bitrate?: number;
  videoCodec?: string;
  audioCodec?: string;
}

export function upsertOverlayCapture(items: readonly OverlayCapture[], capture: OverlayCapture, limit = 5): OverlayCapture[] {
  return [capture, ...items.filter(item => item.id !== capture.id)].slice(0, Math.max(1, limit));
}

export function formatContentLength(bytes: number | undefined): string {
  if (!bytes || bytes < 1) return '大小未知';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1000;
  let unit = units[0];
  for (let index = 0; value >= 1024 && index < units.length - 1; index += 1) {
    value /= 1000;
    unit = units[index + 1];
  }
  return `${value.toFixed(value >= 100 ? 0 : 2)} ${unit}`;
}

export function qualityLabel(capture: Pick<OverlayCapture, 'url' | 'title'>): string | undefined {
  const match = `${capture.title ?? ''} ${capture.url}`.match(/(?:2160|1440|1080|720|540|480|360|240)p\b/i);
  return match?.[0].toLowerCase();
}

export function mediaSourceLabel(url: string): string {
  try {
    const parsed = new URL(url);
    const source = `${parsed.host}${parsed.pathname}`;
    if (source.length <= 72) return source;
    return `${source.slice(0, 34)}...${source.slice(-34)}`;
  } catch {
    return url.length <= 72 ? url : `${url.slice(0, 34)}...${url.slice(-34)}`;
  }
}

function formatBitrate(bitsPerSecond: number): string {
  if (bitsPerSecond >= 1_000_000) return `${(bitsPerSecond / 1_000_000).toFixed(2)} Mbps`;
  return `${Math.round(bitsPerSecond / 1_000)} Kbps`;
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
}

export function mediaInfoLabel(info: MediaInfo): string {
  const parts: string[] = [];
  if (info.width && info.height) parts.push(`${info.width}x${info.height}`);
  if (info.bitrate && info.bitrate > 0) parts.push(formatBitrate(info.bitrate));
  if (info.duration && info.duration > 0) parts.push(formatDuration(info.duration));
  return parts.join(' · ') || '媒体信息待探测';
}

function positiveNumber(value: string | undefined): number | undefined {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : undefined;
}

function parseAttributes(value: string): Map<string, string> {
  const attributes = new Map<string, string>();
  for (const match of value.matchAll(/([A-Z0-9-]+)=("[^"]*"|[^,]*)/gi)) {
    attributes.set(match[1].toUpperCase(), match[2].replace(/^"|"$/g, '').trim());
  }
  return attributes;
}

function codecParts(value: string | undefined): Pick<MediaRendition, 'videoCodec' | 'audioCodec'> {
  const codecs = (value ?? '').split(',').map(codec => codec.trim()).filter(Boolean);
  return {
    videoCodec: codecs.find(codec => !/^(?:mp4a|ac-3|ec-3|opus|vorbis)/i.test(codec)),
    audioCodec: codecs.find(codec => /^(?:mp4a|ac-3|ec-3|opus|vorbis)/i.test(codec)),
  };
}

function resolution(value: string | undefined): Pick<MediaRendition, 'width' | 'height'> {
  const match = value?.match(/^(\d+)x(\d+)$/i);
  return match ? { width: Number(match[1]), height: Number(match[2]) } : {};
}

function compactRendition(rendition: MediaRendition): MediaRendition {
  return Object.fromEntries(Object.entries(rendition).filter(([, value]) => value !== undefined)) as MediaRendition;
}

function parseHlsManifest(text: string, baseUrl: string): MediaInfo {
  const lines = text.replace(/\r/g, '').split('\n').map(line => line.trim());
  const renditions: MediaRendition[] = [];
  let duration = 0;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.startsWith('#EXT-X-STREAM-INF:')) {
      const attributes = parseAttributes(line.slice('#EXT-X-STREAM-INF:'.length));
      const uri = lines.slice(index + 1).find(candidate => candidate && !candidate.startsWith('#'));
      if (!uri) continue;
      const bandwidth = positiveNumber(attributes.get('BANDWIDTH')) ?? positiveNumber(attributes.get('AVERAGE-BANDWIDTH'));
      renditions.push(compactRendition({
        id: uri,
        url: new URL(uri, baseUrl).href,
        ...resolution(attributes.get('RESOLUTION')),
        bitrate: bandwidth,
        ...codecParts(attributes.get('CODECS')),
      }));
    }
    const durationMatch = line.match(/^#EXTINF:([\d.]+)/i);
    if (durationMatch) duration += Number(durationMatch[1]);
  }
  return compactRenditions({ duration: duration > 0 ? duration : undefined, renditions });
}

function parseIsoDuration(value: string | undefined): number | undefined {
  const match = value?.match(/^P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$/i);
  if (!match) return undefined;
  return (Number(match[1] ?? 0) * 86400) + (Number(match[2] ?? 0) * 3600) + (Number(match[3] ?? 0) * 60) + Number(match[4] ?? 0);
}

function parseDashManifest(text: string): MediaInfo {
  const mpd = text.match(/<MPD\b([^>]*)>/i)?.[1] ?? '';
  const mpdAttributes = parseAttributes(mpd.replace(/\s+(\w+)=/g, ', $1='));
  const duration = parseIsoDuration(mpdAttributes.get('MEDIAPRESENTATIONDURATION'));
  const renditions: MediaRendition[] = [];
  for (const match of text.matchAll(/<Representation\b([^>]*)>/gi)) {
    const attributes = parseAttributes(match[1].replace(/\s+(\w+)=/g, ', $1='));
    renditions.push(compactRendition({
      id: attributes.get('ID') ?? `representation-${renditions.length + 1}`,
      ...resolution(attributes.get('WIDTH') && attributes.get('HEIGHT') ? `${attributes.get('WIDTH')}x${attributes.get('HEIGHT')}` : undefined),
      bitrate: positiveNumber(attributes.get('BANDWIDTH')),
      ...codecParts(attributes.get('CODECS')),
    }));
  }
  return compactRenditions({ duration, renditions });
}

function compactRenditions(info: MediaInfo): MediaInfo {
  return {
    ...info,
    ...(info.renditions?.length ? { renditions: info.renditions } : {}),
  };
}

export function parseManifestMetadata(text: string, baseUrl: string, kind: 'hls' | 'dash'): MediaInfo {
  try {
    return kind === 'hls' ? parseHlsManifest(text, baseUrl) : parseDashManifest(text);
  } catch {
    return {};
  }
}
