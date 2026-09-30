import test from 'node:test';
import assert from 'node:assert/strict';
import { formatContentLength, mediaInfoLabel, mediaSourceLabel, parseManifestMetadata, qualityLabel, upsertOverlayCapture, type OverlayCapture } from './overlay-state.ts';

const capture = (id: string, title = id) => ({
  id,
  url: `https://media.example.test/${id}.mp4`,
  title,
  kind: 'direct' as const,
  contentLength: 2_000_000,
});

test('puts the newest capture first and removes an older copy', () => {
  const first = upsertOverlayCapture([], capture('first'));
  const next = upsertOverlayCapture(first, capture('second'));
  const refreshed = upsertOverlayCapture(next, capture('first', 'renamed'));

  assert.deepEqual(refreshed.map(item => item.id), ['first', 'second']);
  assert.equal(refreshed[0].title, 'renamed');
});

test('keeps only the five most recent captures', () => {
  let items: OverlayCapture[] = [];
  for (let index = 0; index < 7; index += 1) items = upsertOverlayCapture(items, capture(`capture-${index}`));

  assert.deepEqual(items.map(item => item.id), ['capture-6', 'capture-5', 'capture-4', 'capture-3', 'capture-2']);
});

test('formats capture sizes for the floating card', () => {
  assert.equal(formatContentLength(undefined), '大小未知');
  assert.equal(formatContentLength(27_880_000), '27.88 MB');
  assert.equal(formatContentLength(850), '850 B');
});

test('extracts a stream quality label without dropping other renditions', () => {
  assert.equal(qualityLabel({ ...capture('stream-1080'), url: 'https://media.example.test/movie_1080p.mp4' }), '1080p');
  assert.equal(qualityLabel({ ...capture('stream-720'), title: 'movie 720p' }), '720p');
  assert.equal(qualityLabel(capture('stream-unknown')), undefined);
});

test('formats a compact source label without exposing a long query string', () => {
  const label = mediaSourceLabel('https://video.example.test/o1/v/t2/f2/m412/very-long-resource-name.mp4?token=secret&media_id=123');
  assert.equal(label, 'video.example.test/o1/v/t2/f2/m412/very-long-resource-name.mp4');
  assert.equal(mediaSourceLabel('https://video.example.test/a/'.padEnd(120, 'x')), 'video.example.test/a/xxxxxxxxxxxxx...xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx');
});

test('formats browser media metadata for the resource row', () => {
  assert.equal(mediaInfoLabel({ width: 1920, height: 1080, duration: 266, bitrate: 3_200_000 }), '1920x1080 · 3.20 Mbps · 04:26');
  assert.equal(mediaInfoLabel({ width: 854, height: 480 }), '854x480');
  assert.equal(mediaInfoLabel({}), '媒体信息待探测');
});

test('parses every HLS master rendition with bitrate and resolution', () => {
  const info = parseManifestMetadata(`#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=51000,AVERAGE-BANDWIDTH=48000,RESOLUTION=854x480,CODECS="avc1.4d401f,mp4a.40.2"
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1177000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
high/index.m3u8`, 'https://media.example.test/master.m3u8', 'hls');

  assert.deepEqual(info.renditions, [
    { id: 'low/index.m3u8', url: 'https://media.example.test/low/index.m3u8', width: 854, height: 480, bitrate: 51_000, videoCodec: 'avc1.4d401f', audioCodec: 'mp4a.40.2' },
    { id: 'high/index.m3u8', url: 'https://media.example.test/high/index.m3u8', width: 1920, height: 1080, bitrate: 1_177_000, videoCodec: 'avc1.640028', audioCodec: 'mp4a.40.2' },
  ]);
});

test('parses DASH representations and media duration', () => {
  const info = parseManifestMetadata(`<MPD mediaPresentationDuration="PT1M26.5S"><Period><AdaptationSet contentType="video"><Representation id="v480" bandwidth="51000" width="854" height="480" codecs="avc1.4d401f"/><Representation id="v1080" bandwidth="1177000" width="1920" height="1080" codecs="avc1.640028"/></AdaptationSet></Period></MPD>`, 'https://media.example.test/manifest.mpd', 'dash');

  assert.equal(info.duration, 86.5);
  assert.deepEqual(info.renditions, [
    { id: 'v480', width: 854, height: 480, bitrate: 51_000, videoCodec: 'avc1.4d401f' },
    { id: 'v1080', width: 1920, height: 1080, bitrate: 1_177_000, videoCodec: 'avc1.640028' },
  ]);
});
