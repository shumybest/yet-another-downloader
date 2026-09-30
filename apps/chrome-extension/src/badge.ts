import type { Capture } from '@m3u8-bridge/protocol';

export function formatBadgeCount(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return '';
  return count > 99 ? '99+' : String(Math.floor(count));
}

export async function updateTabBadge(tabId: number, captures: Capture[]): Promise<void> {
  const ids = new Set(
    captures
      .filter(capture => capture.tabId === tabId)
      .map(capture => capture.id || `${capture.kind}:${capture.url}`),
  );
  await Promise.all([
    chrome.action.setBadgeBackgroundColor({ tabId, color: '#b7f36b' }),
    chrome.action.setBadgeText({ tabId, text: formatBadgeCount(ids.size) }),
  ]);
}
