import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyMedia, contentLengthFromResponse, fingerprint, isHlsUrl, isMediaUrl, titleFromUrl } from './index.ts';

test('recognizes HLS URLs and content types', () => {
  assert.equal(isHlsUrl('https://example.test/stream/master.m3u8?x=1'), true);
  assert.equal(isHlsUrl('https://example.test/video', 'application/vnd.apple.mpegurl'), true);
  assert.equal(isHlsUrl('https://example.test/video.mp4', 'video/mp4'), false);
});

test('creates stable capture fingerprints', () => {
  assert.equal(fingerprint('https://a.test/master.m3u8', 3), '3:https://a.test/master.m3u8');
  assert.equal(titleFromUrl('https://a.test/path/my%20video.m3u8'), 'my video');
});

test('classifies DASH manifests and direct video MIME types', () => {
  assert.equal(classifyMedia('https://a.test/live/manifest.mpd', ''), 'dash');
  assert.equal(classifyMedia('https://a.test/download?id=7', 'video/mp4; codecs="avc1.640028"'), 'direct');
  assert.equal(classifyMedia('https://a.test/download?id=7', 'video/webm'), 'direct');
  assert.equal(isMediaUrl('https://a.test/clip.mov', ''), true);
});

test('does not surface common streaming fragments as standalone captures', () => {
  assert.equal(classifyMedia('https://a.test/video/segment-001.m4s', 'video/iso.segment'), null);
  assert.equal(classifyMedia('https://a.test/video/chunk.ts', 'video/mp2t'), null);
  assert.equal(classifyMedia('https://a.test/video/chunk-001.mp4', 'video/mp4'), null);
  assert.equal(classifyMedia('https://a.test/video/chunk-001', 'application/octet-stream', { resourceType: 'media' }), null);
  assert.equal(classifyMedia('https://a.test/player.js', 'application/javascript'), null);
});

test('recognizes media resources without a video extension', () => {
  assert.equal(classifyMedia('https://a.test/download?id=7', 'application/octet-stream', { resourceType: 'media' }), 'direct');
  assert.equal(classifyMedia('https://a.test/file?id=7', 'application/octet-stream', {
    contentDisposition: 'attachment; filename="muse-video.mp4"',
  }), 'direct');
  assert.equal(classifyMedia('https://a.test/file?id=7', 'application/octet-stream', {
    contentDisposition: "attachment; filename*=UTF-8''muse%20video.webm",
  }), 'direct');
});

test('prefers a valid content range total when content length is unavailable', () => {
  assert.equal(contentLengthFromResponse(undefined, 'bytes 0-99/1000'), 1000);
  assert.equal(contentLengthFromResponse('250', 'bytes 0-99/1000'), 250);
  assert.equal(contentLengthFromResponse(undefined, 'bytes 0-99/*'), undefined);
});

test('titles strip common media extensions', () => {
  assert.equal(titleFromUrl('https://a.test/path/my%20video.webm?range=1'), 'my video');
  assert.equal(titleFromUrl('https://a.test/path/live.mpd'), 'live');
});
