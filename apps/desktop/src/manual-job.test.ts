import assert from 'node:assert/strict';
import test from 'node:test';
import { buildManualJobRequest } from './manual-job.ts';

test('creates a capture from a signed media URL without rewriting it', () => {
  const url = ' https://media.example.test/master.m3u8?token=abc%2Fdef&quality=high ';
  assert.deepEqual(buildManualJobRequest(url, '  比赛录像  '), {
    capture: { url: url.trim(), title: '比赛录像' },
  });
});

test('allows a media URL without a custom title', () => {
  assert.deepEqual(buildManualJobRequest('http://media.example.test/video.mp4', '  '), {
    capture: { url: 'http://media.example.test/video.mp4' },
  });
});

test('allows explicitly classifying an extensionless media URL', () => {
  assert.deepEqual(buildManualJobRequest('https://media.example.test/play?id=7', '', 'direct'), {
    capture: { url: 'https://media.example.test/play?id=7', kind: 'direct' },
  });
});

test('rejects missing or non-HTTP media URLs', () => {
  assert.throws(() => buildManualJobRequest('   ', ''), /请输入媒体地址/);
  assert.throws(() => buildManualJobRequest('file:///tmp/video.mp4', ''), /HTTP 或 HTTPS/);
  assert.throws(() => buildManualJobRequest('https://', ''), /有效的媒体地址/);
  assert.throws(() => buildManualJobRequest('https://media.example.test/video file.mp4', ''), /有效的媒体地址/);
});
