import assert from 'node:assert/strict';
import test from 'node:test';
import { startupElapsed, startupStepState } from './engine-startup.ts';

test('shows yt-dlp load as current, earlier steps complete, API check waiting', () => {
  assert.equal(startupStepState('ytdlp', 3), 'complete');
  assert.equal(startupStepState('ytdlp', 4), 'current');
  assert.equal(startupStepState('ytdlp', 5), 'waiting');
  assert.equal(startupStepState('ready', 5), 'complete');
});

test('shows long cold starts without invented percentage progress', () => {
  assert.equal(startupElapsed(65_400), '1 分 5 秒');
  assert.equal(startupElapsed(900), '0 秒');
});
