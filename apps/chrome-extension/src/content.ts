import { formatContentLength, mediaInfoLabel, mediaSourceLabel, parseManifestMetadata, qualityLabel, type MediaInfo, type OverlayCapture, type MediaRendition, upsertOverlayCapture } from './overlay-state.ts';

const HOST_ID = '__m3u8_bridge_overlay__';
const MAX_ITEMS = 20;
const ROW_HEIGHT = 38;
const HEADER_HEIGHT = 30;

type BarStatus = 'idle' | 'submitting' | 'submitted' | 'error';

let captures: OverlayCapture[] = [];
const dismissed = new Set<string>();
const anchors = new Map<string, HTMLElement>();
const statuses = new Map<string, BarStatus>();
let activeAnchor: HTMLElement | null = null;
let hoveredAnchor: HTMLElement | null = null;
let host: HTMLDivElement | null = null;
let renderScheduled = false;

function kindLabel(kind: OverlayCapture['kind']): string {
  return ({ hls: 'HLS', dash: 'DASH', direct: 'MP4' }[kind || 'direct']);
}

function createElement<K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text?: string): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

function isVisible(element: HTMLElement): boolean {
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  return rect.width > 32 && rect.height > 20 && rect.bottom > 0 && rect.top < window.innerHeight
    && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0;
}

function sourceValues(element: HTMLElement): string[] {
  const values = [
    element.getAttribute('src'),
    element.getAttribute('data-src'),
    element.getAttribute('data-url'),
    element.getAttribute('data-video-url'),
    element.getAttribute('href'),
    element instanceof HTMLMediaElement ? element.currentSrc : null,
    element instanceof HTMLMediaElement ? element.src : null,
  ];
  if (element instanceof HTMLMediaElement) {
    values.push(...Array.from(element.querySelectorAll('source')).flatMap(source => [source.getAttribute('src'), source.getAttribute('data-src')]));
  }
  return values.filter((value): value is string => Boolean(value));
}

function sameMediaPath(left: string, right: string): boolean {
  try {
    const first = new URL(left, location.href);
    const second = new URL(right, location.href);
    return first.href === second.href || (first.origin === second.origin && first.pathname === second.pathname);
  } catch {
    return left === right;
  }
}

function mediaAnchor(element: HTMLElement): HTMLElement {
  return element.tagName === 'SOURCE' && element.parentElement instanceof HTMLElement ? element.parentElement : element;
}

function visibleVideos(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('video')).filter(isVisible)
    .sort((left, right) => right.getBoundingClientRect().width * right.getBoundingClientRect().height
      - left.getBoundingClientRect().width * left.getBoundingClientRect().height);
}

function findAnchor(capture: OverlayCapture): HTMLElement | null {
  const candidates = Array.from(document.querySelectorAll<HTMLElement>(
    'video, source, [src], [data-src], [data-url], [data-video-url], a[href]',
  )).filter(isVisible).map(mediaAnchor);
  const exact = candidates.find(candidate => sourceValues(candidate).some(value => sameMediaPath(value, capture.url)));
  if (exact) return exact;

  const assigned = new Set(anchors.values());
  return visibleVideos().find(video => !assigned.has(video)) ?? visibleVideos()[0] ?? null;
}

function capturesForAnchor(anchor: HTMLElement): OverlayCapture[] {
  return captures.filter(capture => anchors.get(capture.id) === anchor && !dismissed.has(capture.id));
}

function anchorForTarget(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null;
  for (const anchor of new Set(anchors.values())) {
    if (anchor === target || anchor.contains(target)) return anchor;
  }
  const candidate = target.closest<HTMLElement>('video, [src], [data-src], [data-url], [data-video-url], a[href]');
  return candidate ? mediaAnchor(candidate) : null;
}

function ensureHost(): ShadowRoot {
  if (!host) {
    host = document.createElement('div');
    host.id = HOST_ID;
    host.style.position = 'fixed';
    host.style.inset = '0';
    host.style.zIndex = '2147483647';
    host.style.pointerEvents = 'none';
    document.documentElement.appendChild(host);
  }
  return host.shadowRoot ?? host.attachShadow({ mode: 'open' });
}

function removeHost(): void {
  host?.remove();
  host = null;
}

function scheduleRender(): void {
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    render();
  });
}

function closeActiveGroup(): void {
  if (activeAnchor) capturesForAnchor(activeAnchor).forEach(capture => dismissed.add(capture.id));
  activeAnchor = null;
  removeHost();
}

function dismissCapture(id: string): void {
  dismissed.add(id);
  captures = captures.filter(capture => capture.id !== id);
  anchors.delete(id);
  statuses.delete(id);
  if (activeAnchor && !capturesForAnchor(activeAnchor).length) activeAnchor = null;
  scheduleRender();
}

function submitCapture(capture: OverlayCapture): void {
  const currentStatus = statuses.get(capture.id);
  if (currentStatus === 'submitting' || currentStatus === 'submitted') return;
  statuses.set(capture.id, 'submitting');
  scheduleRender();
  void chrome.runtime.sendMessage({ type: 'download-capture', captureId: capture.id }).then(response => {
    statuses.set(capture.id, response?.ok ? 'submitted' : 'error');
    scheduleRender();
  }).catch(() => {
    statuses.set(capture.id, 'error');
    scheduleRender();
  });
}

function videoForAnchor(anchor: HTMLElement): HTMLVideoElement | null {
  return anchor instanceof HTMLVideoElement ? anchor : anchor.querySelector('video');
}

function reportMediaInfo(capture: OverlayCapture, mediaInfo: MediaInfo): void {
  if (!Object.values(mediaInfo).some(value => value != null)) return;
  void chrome.runtime.sendMessage({ type: 'enrich-capture', captureId: capture.id, mediaInfo });
}

function readMediaInfo(video: HTMLVideoElement, capture: OverlayCapture): MediaInfo {
  const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : undefined;
  return {
    width: video.videoWidth || undefined,
    height: video.videoHeight || undefined,
    duration,
    bitrate: capture.kind === 'direct' && capture.contentLength && duration
      ? capture.contentLength * 8 / duration
      : undefined,
  };
}

function enrichCapture(capture: OverlayCapture, anchor: HTMLElement): void {
  const video = videoForAnchor(anchor);
  const reportVideo = () => {
    if (!video) return;
    const mediaInfo = readMediaInfo(video, capture);
    reportMediaInfo(capture, mediaInfo);
  };
  if (video?.readyState && video.readyState >= HTMLMediaElement.HAVE_METADATA) reportVideo();
  else video?.addEventListener('loadedmetadata', reportVideo, { once: true });
  window.setTimeout(reportVideo, 1500);

  if (capture.kind === 'hls' || capture.kind === 'dash') {
    void fetch(capture.url, { credentials: 'include', cache: 'no-store' })
      .then(response => response.ok ? response.text() : Promise.reject(new Error('manifest unavailable')))
      .then(text => reportMediaInfo(capture, parseManifestMetadata(text, capture.url, capture.kind as 'hls' | 'dash')))
      .catch(() => undefined);
  }
}

function renditionLabel(rendition: MediaRendition): string {
  const parts: string[] = [];
  if (rendition.width && rendition.height) parts.push(`${rendition.width}x${rendition.height}`);
  if (rendition.bitrate) parts.push(rendition.bitrate >= 1_000_000 ? `${(rendition.bitrate / 1_000_000).toFixed(2)} Mbps` : `${Math.round(rendition.bitrate / 1_000)} Kbps`);
  if (rendition.videoCodec) parts.push(rendition.videoCodec);
  if (rendition.audioCodec) parts.push(rendition.audioCodec);
  return parts.join(' · ') || rendition.id;
}

function render(): void {
  if (!activeAnchor || !activeAnchor.isConnected || !isVisible(activeAnchor)) {
    removeHost();
    return;
  }
  const group = capturesForAnchor(activeAnchor);
  if (!group.length) {
    removeHost();
    return;
  }

  const root = ensureHost();
  root.replaceChildren();
  const style = document.createElement('style');
  style.textContent = `
    :host { all: initial; }
    *, *::before, *::after { box-sizing: border-box; }
    .panel { position: fixed; width: min(320px, calc(100vw - 16px)); max-width: calc(100vw - 16px); max-height: min(70vh, 620px); overflow-x: hidden; overflow-y: auto; border: 1px solid rgba(16, 32, 43, .62); border-radius: 8px; background: rgba(220, 234, 242, .98); box-shadow: 0 4px 14px rgba(10, 25, 35, .3); color: #10202b; font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; pointer-events: auto; }
    .head { display: flex; align-items: center; justify-content: space-between; min-width: 0; min-height: 30px; padding: 5px 7px 5px 10px; border-bottom: 1px solid rgba(16, 32, 43, .25); font-size: 11px; font-weight: 800; }
    .head-label { display: flex; min-width: 0; align-items: center; gap: 6px; overflow-wrap: anywhere; word-break: break-word; white-space: normal; }
    .pulse { width: 7px; height: 7px; border-radius: 50%; background: #39a96b; box-shadow: 0 0 0 3px rgba(57, 169, 107, .16); }
    .close-all, .dismiss { appearance: none; border: 0; cursor: pointer; line-height: 1; }
    .close-all { padding: 2px 3px; color: #4e6570; background: transparent; font-size: 15px; font-weight: 900; }
    .row { display: flex; width: 100%; align-items: flex-start; gap: 7px; min-height: 38px; padding: 5px 6px 5px 8px; border-bottom: 1px solid rgba(16, 32, 43, .15); }
    .row:last-child { border-bottom: 0; }
    .download { display: flex; width: 0; flex: 1 1 0; align-items: center; gap: 7px; min-width: 0; padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer; text-align: left; }
    .download:disabled { cursor: wait; opacity: .7; }
    .icon { display: grid; flex: 0 0 24px; place-items: center; width: 24px; height: 24px; border-radius: 6px; color: #f4fbff; background: #39a96b; font-size: 8px; font-weight: 900; }
    .copy { display: block; width: 0; max-width: 100%; flex: 1 1 auto; min-width: 0; overflow: hidden; }
    .title, .meta { display: block; max-width: 100%; overflow: hidden; overflow-wrap: anywhere; word-break: break-all; white-space: normal; }
    .title { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
    .title { font-size: 11px; font-weight: 800; }
    .meta { margin-top: 2px; color: #58707c; font-size: 9px; }
    .renditions { display: grid; max-width: 100%; gap: 2px; margin-top: 4px; }
    .rendition { max-width: 100%; overflow: hidden; overflow-wrap: anywhere; word-break: break-all; color: #31515d; font-size: 9px; white-space: normal; }
    .dismiss { flex: 0 0 21px; width: 21px; height: 21px; padding: 0; border-radius: 50%; background: #ff5a56; box-shadow: 0 1px 2px rgba(70, 20, 20, .3); color: white; font-size: 15px; font-weight: 900; }
    .dismiss:hover, .dismiss:focus-visible { background: #d92d2a; }
  `;
  root.appendChild(style);

  const rect = activeAnchor.getBoundingClientRect();
  const width = Math.max(0, Math.min(320, window.innerWidth - 16));
  const renditionCount = group.reduce((total, capture) => total + Math.max(0, capture.mediaInfo?.renditions?.length ?? 0), 0);
  const maxHeight = Math.max(0, Math.min(620, window.innerHeight - 16));
  const estimatedHeight = HEADER_HEIGHT + group.reduce((total, capture) => total + ROW_HEIGHT + (capture.mediaInfo?.renditions?.length ?? 0) * 24, 0);
  const height = Math.min(maxHeight, estimatedHeight);
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width - 5));
  let top = rect.top - height - 4;
  if (top < 8) top = Math.min(window.innerHeight - height - 8, rect.top + 5);

  const panel = createElement('section', 'panel');
  panel.style.left = `${left}px`;
  panel.style.top = `${Math.max(8, top)}px`;
  const head = createElement('header', 'head');
  const label = createElement('span', 'head-label');
  label.append(createElement('i', 'pulse'), document.createTextNode(`发现媒体 · ${group.length}路${renditionCount ? ` · ${renditionCount}档` : ''}`));
  const closeAll = createElement('button', 'close-all', '×');
  closeAll.type = 'button';
  closeAll.title = '关闭此视频的下载提示';
  closeAll.setAttribute('aria-label', '关闭此视频的下载提示');
  closeAll.addEventListener('click', closeActiveGroup);
  head.append(label, closeAll);
  panel.appendChild(head);

  for (const capture of group) {
    const row = createElement('div', 'row');
    const download = createElement('button', 'download');
    download.type = 'button';
    const icon = createElement('span', 'icon', kindLabel(capture.kind));
    const copy = createElement('span', 'copy');
    const status = statuses.get(capture.id) ?? 'idle';
    const quality = qualityLabel(capture);
    const size = formatContentLength(capture.contentLength);
    const title = status === 'submitted' ? '已提交下载任务' : status === 'error' ? '提交失败，点击重试' : `${quality ? `${quality} · ` : ''}${kindLabel(capture.kind)} ${size}`;
    copy.append(createElement('strong', 'title', title));
    copy.append(createElement('span', 'meta', `${mediaInfoLabel(capture.mediaInfo ?? {})} · ${mediaSourceLabel(capture.url)}`));
    const renditions = capture.mediaInfo?.renditions ?? [];
    if (renditions.length) {
      const renditionList = createElement('span', 'renditions');
      for (const rendition of renditions) renditionList.append(createElement('span', 'rendition', `码流 ${renditionLabel(rendition)}`));
      copy.append(renditionList);
    }
    download.append(icon, copy);
    download.disabled = status === 'submitting' || status === 'submitted';
    download.addEventListener('click', () => submitCapture(capture));
    const dismiss = createElement('button', 'dismiss', '×');
    dismiss.type = 'button';
    dismiss.title = '移除这个码流';
    dismiss.setAttribute('aria-label', '移除这个码流');
    dismiss.addEventListener('click', event => { event.stopPropagation(); dismissCapture(capture.id); });
    row.append(download, dismiss);
    panel.appendChild(row);
  }
  root.appendChild(panel);
}

function acceptCapture(capture: OverlayCapture): void {
  if (!capture.id || dismissed.has(capture.id)) return;
  captures = upsertOverlayCapture(captures, capture, MAX_ITEMS);
  const anchor = hoveredAnchor && isVisible(hoveredAnchor) ? hoveredAnchor : findAnchor(capture);
  if (anchor) {
    anchors.set(capture.id, anchor);
    enrichCapture(capture, anchor);
    if (!activeAnchor || hoveredAnchor === anchor) activeAnchor = anchor;
  }
  scheduleRender();
}

document.addEventListener('mouseover', event => {
  const next = anchorForTarget(event.target);
  if (!next || next === hoveredAnchor) return;
  hoveredAnchor = next;
  if (capturesForAnchor(next).length) {
    activeAnchor = next;
    scheduleRender();
  }
}, true);

chrome.runtime.onMessage.addListener(message => {
  if (message?.type === 'media-capture') acceptCapture(message.capture as OverlayCapture);
  if (message?.type === 'media-capture-updated') {
    const updated = message.capture as OverlayCapture;
    const index = captures.findIndex(capture => capture.id === updated.id);
    if (index >= 0) captures[index] = { ...captures[index], ...updated };
    scheduleRender();
  }
});

void chrome.runtime.sendMessage({ type: 'get-page-captures', pageUrl: location.href }).then(response => {
  for (const capture of (response?.captures ?? []) as OverlayCapture[]) acceptCapture(capture);
}).catch(() => undefined);

window.addEventListener('scroll', scheduleRender, true);
window.addEventListener('resize', scheduleRender);
new MutationObserver(scheduleRender).observe(document.documentElement ?? document, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ['src', 'data-src', 'data-url', 'data-video-url', 'style', 'class'],
});
