import type { CreateJobRequest, MediaKind } from '@m3u8-bridge/protocol';

export function buildManualJobRequest(urlInput: string, titleInput: string, kind?: MediaKind): CreateJobRequest {
  const url = urlInput.trim();
  if (!url) throw new Error('请输入媒体地址');
  if (/\s/.test(url)) throw new Error('请输入有效的媒体地址，空格请使用 URL 编码');

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error('请输入有效的媒体地址');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('仅支持 HTTP 或 HTTPS 媒体地址');
  }

  const title = titleInput.trim();
  return { capture: { url, ...(title ? { title } : {}), ...(kind ? { kind } : {}) } };
}
