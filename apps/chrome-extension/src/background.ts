import { classifyMedia, contentLengthFromResponse, fingerprint, normalizeHeaders, titleFromUrl } from '@m3u8-bridge/capture-core';
import { EngineClient, type Capture, type Job, type MediaInfo, type MediaRendition } from '@m3u8-bridge/protocol';
import { submitWithDesktopLaunch } from './desktop-launch';
import { updateTabBadge } from './badge';

type OverlayCapture = Pick<Capture, 'id' | 'url' | 'title' | 'kind' | 'contentType' | 'contentLength' | 'mediaInfo'>;
type RuntimeMessage =
  | { type: 'get-page-captures'; pageUrl: string }
  | { type: 'download-capture'; captureId: string }
  | { type: 'enrich-capture'; captureId: string; mediaInfo: MediaInfo };

const requestHeaders = new Map<string, chrome.webRequest.HttpHeader[]>();
const seen = new Set<string>();

function toOverlayCapture(capture: Capture): OverlayCapture {
  return {
    id: capture.id,
    url: capture.url,
    title: capture.title,
    kind: capture.kind,
    contentType: capture.contentType,
    contentLength: capture.contentLength,
    mediaInfo: capture.mediaInfo,
  };
}

async function readCaptures(): Promise<Capture[]> {
  const stored = await chrome.storage.session.get('captures');
  return (stored.captures as Capture[] | undefined) ?? [];
}

async function writeCaptures(captures: Capture[]): Promise<void> {
  await chrome.storage.session.set({ captures });
}

async function refreshBadges(captures?: Capture[]): Promise<void> {
  const currentCaptures = captures ?? await readCaptures();
  const tabs = await chrome.tabs.query({});
  await Promise.all(tabs.flatMap(tab => tab.id == null ? [] : [updateTabBadge(tab.id, currentCaptures)]));
}

async function notifyOverlay(tabId: number, capture: Capture): Promise<void> {
  await chrome.tabs.sendMessage(tabId, { type: 'media-capture', capture: toOverlayCapture(capture) }).catch(() => undefined);
}

async function notifyOverlayUpdate(tabId: number, capture: Capture): Promise<void> {
  await chrome.tabs.sendMessage(tabId, { type: 'media-capture-updated', capture: toOverlayCapture(capture) }).catch(() => undefined);
}

function sanitizeMediaInfo(value: MediaInfo): MediaInfo {
  const positive = (candidate: unknown): number | undefined => {
    const number = Number(candidate);
    return Number.isFinite(number) && number > 0 ? number : undefined;
  };
  const renditions = Array.isArray(value.renditions)
    ? value.renditions.slice(0, 20).flatMap((item: MediaRendition) => {
      if (!item || typeof item.id !== 'string') return [];
      const rendition: MediaRendition = {
        id: item.id.slice(0, 200),
        width: positive(item.width),
        height: positive(item.height),
        bitrate: positive(item.bitrate),
        videoCodec: typeof item.videoCodec === 'string' ? item.videoCodec.slice(0, 80) : undefined,
        audioCodec: typeof item.audioCodec === 'string' ? item.audioCodec.slice(0, 80) : undefined,
      };
      return [rendition];
    })
    : undefined;
  return {
    width: positive(value.width),
    height: positive(value.height),
    duration: positive(value.duration),
    bitrate: positive(value.bitrate),
    videoCodec: typeof value.videoCodec === 'string' ? value.videoCodec.slice(0, 80) : undefined,
    audioCodec: typeof value.audioCodec === 'string' ? value.audioCodec.slice(0, 80) : undefined,
    renditions: renditions?.length ? renditions : undefined,
  };
}

chrome.webRequest.onSendHeaders.addListener(details => {
  if (details.requestHeaders) requestHeaders.set(details.requestId, details.requestHeaders);
}, { urls: ['<all_urls>'] }, ['requestHeaders', 'extraHeaders']);

chrome.webRequest.onResponseStarted.addListener(details => {
  void (async () => {
    const responseHeaders = new Map((details.responseHeaders ?? []).map(header => [header.name.toLowerCase(), header.value ?? '']));
    const requestHeaderList = requestHeaders.get(details.requestId);
    requestHeaders.delete(details.requestId);
    const contentType = responseHeaders.get('content-type') ?? '';
    const contentDisposition = responseHeaders.get('content-disposition') ?? undefined;
    const contentRange = responseHeaders.get('content-range') ?? undefined;
    const kind = classifyMedia(details.url, contentType, {
      resourceType: details.type,
      contentDisposition,
    });
    if (!kind) return;
    const tab = details.tabId > 0 ? await chrome.tabs.get(details.tabId).catch(() => undefined) : undefined;
    const headers = normalizeHeaders(requestHeaderList);
    const cookieEntry = Object.entries(headers).find(([key]) => key.toLowerCase() === 'cookie');
    if (cookieEntry) delete headers[cookieEntry[0]];
    const length = contentLengthFromResponse(responseHeaders.get('content-length'), contentRange);
    const capture: Capture = {
      url: details.url,
      pageUrl: tab?.url,
      title: tab?.title || titleFromUrl(details.url),
      tabId: details.tabId,
      headers,
      cookie: cookieEntry?.[1],
      kind,
      contentType: contentType || undefined,
      contentLength: length,
      capturedAt: Date.now(),
    };
    const key = fingerprint(capture.url, capture.tabId, capture.kind);
    if (seen.has(key)) return;
    seen.add(key);
    capture.id = key;
    const captures = [capture, ...(await readCaptures()).filter(item => item.id !== capture.id)].slice(0, 50);
    await writeCaptures(captures);
    if (details.tabId > 0) {
      await Promise.all([notifyOverlay(details.tabId, capture), updateTabBadge(details.tabId, captures)]);
    }
  })();
}, { urls: ['<all_urls>'] }, ['responseHeaders', 'extraHeaders']);

chrome.webRequest.onErrorOccurred.addListener(details => requestHeaders.delete(details.requestId), { urls: ['<all_urls>'] });

chrome.runtime.onMessage.addListener((message: RuntimeMessage, sender, sendResponse) => {
  if (message.type === 'get-page-captures') {
    void (async () => {
      const tabId = sender.tab?.id;
      const topLevelPageUrl = sender.tab?.url;
      const captures = tabId == null
        ? []
        : (await readCaptures()).filter(capture => capture.tabId === tabId
          && (capture.pageUrl === message.pageUrl || capture.pageUrl === topLevelPageUrl)).map(toOverlayCapture);
      sendResponse({ captures });
    })();
    return true;
  }

  if (message.type === 'download-capture') {
    void (async () => {
      try {
        const capture = (await readCaptures()).find(item => item.id === message.captureId);
        if (!capture) throw new Error('Media capture is no longer available');
        const client = new EngineClient();
        const job = await submitWithDesktopLaunch(
          () => client.createJob({ capture }),
          url => chrome.tabs.create({ url }),
        );
        void client.activateApp().catch(() => undefined);
        sendResponse({ ok: true, jobId: (job as Job).id });
      } catch (error) {
        sendResponse({ ok: false, error: error instanceof Error ? error.message : '本地引擎未启动或资源已失效' });
      }
    })();
    return true;
  }

  if (message.type === 'enrich-capture') {
    void (async () => {
      const captures = await readCaptures();
      const capture = captures.find(item => item.id === message.captureId);
      if (!capture) { sendResponse({ ok: false }); return; }
      const nextInfo = sanitizeMediaInfo(message.mediaInfo);
      capture.mediaInfo = {
        ...(capture.mediaInfo ?? {}),
        ...Object.fromEntries(Object.entries(nextInfo).filter(([, value]) => value !== undefined)),
      };
      await writeCaptures(captures);
      if (capture.tabId && capture.tabId > 0) await notifyOverlayUpdate(capture.tabId, capture);
      sendResponse({ ok: true });
    })().catch(() => sendResponse({ ok: false }));
    return true;
  }

  return false;
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!changeInfo.url) return;
  void (async () => {
    const captures = (await readCaptures()).filter(capture => capture.tabId !== tabId);
    await writeCaptures(captures);
    await updateTabBadge(tabId, captures);
  })();
});

chrome.tabs.onRemoved.addListener(tabId => {
  void (async () => {
    const captures = (await readCaptures()).filter(capture => capture.tabId !== tabId);
    await writeCaptures(captures);
  })();
});

chrome.runtime.onStartup.addListener(() => { void refreshBadges(); });
chrome.runtime.onInstalled.addListener(() => { void refreshBadges(); });
void refreshBadges().catch(() => undefined);
