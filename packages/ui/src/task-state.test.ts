import test from 'node:test';
import assert from 'node:assert/strict';
import { aggregateTaskMetrics, canRetryTask, formatBytes, formatSpeed, taskMatchesFilter } from './task-state.ts';

const job = (status: 'queued' | 'failed' | 'completed' | 'cancelled', canRetry = false) => ({
  id: 'job', status, title: 'clip', url: 'https://media.example/clip.m3u8', progress: 0, downloadedFragments: 0, createdAt: 0, updatedAt: 0, canRetry,
});

test('formats byte counts and speeds for the task list', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(1024), '1.0 KiB');
  assert.equal(formatSpeed(1024 * 1024), '1.0 MiB/s');
});

test('matches task filters and retry availability', () => {
  assert.equal(taskMatchesFilter(job('queued'), 'active'), true);
  assert.equal(taskMatchesFilter(job('completed'), 'active'), false);
  assert.equal(taskMatchesFilter(job('failed', true), 'failed'), true);
  assert.equal(canRetryTask(job('failed', true)), true);
  assert.equal(canRetryTask(job('completed', true)), false);
});

test('aggregates active jobs, live speed and downloaded bytes', () => {
  const metrics = aggregateTaskMetrics([
    { ...job('queued'), speedBytesPerSecond: 1024, downloadedBytes: 2048 },
    { ...job('completed'), speedBytesPerSecond: 9999, downloadedBytes: 4096 },
    { ...job('failed'), speedBytesPerSecond: 9999, downloadedBytes: 512 },
  ]);

  assert.deepEqual(metrics, { active: 1, speedBytesPerSecond: 1024, downloadedBytes: 6656 });
});

test('processing uses stage progress instead of stale download percentage', async () => {
  const { processingView } = await import('./task-state.ts');
  const view = processingView({ ...job('queued'), status: 'muxing', progress: 99,
    processingStage: 'transcoding', processingProgress: 25, processingSeconds: 30,
    processingDuration: 120, processingSpeed: '0.5x', processingStartedAt: 1000 }, 61000);
  assert.equal(view?.label, '转码为 H.264');
  assert.equal(view?.percent, 25);
  assert.match(view?.detail || '', /0:30 \/ 2:00.*0.5x.*1:00/);
  assert.equal(processingView({ ...job('queued'), status: 'muxing' })?.percent, null);
  assert.equal(processingView(job('completed')), null);
});
