import assert from 'node:assert/strict';
import test from 'node:test';
import { assertCompatibleHealth } from './compatibility.ts';

test('accepts an engine that advertises job deletion', () => {
  assert.doesNotThrow(() => assertCompatibleHealth({
    ok: true,
    version: '0.1.0',
    apiRevision: 2,
    capabilities: ['jobs.delete'],
    ffmpeg: '/usr/local/bin/ffmpeg',
    ytDlp: '2026.08.19',
  }));
});

test('rejects a healthy legacy engine without the deletion API', () => {
  assert.throws(
    () => assertCompatibleHealth({
      ok: true,
      version: '0.1.0',
      ffmpeg: '/usr/local/bin/ffmpeg',
      ytDlp: '2026.08.19',
    }),
    /接口版本过旧/,
  );
});
