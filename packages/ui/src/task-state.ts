import type { Job } from '@m3u8-bridge/protocol';

export type TaskFilter = 'all' | 'active' | 'completed' | 'failed' | 'cancelled';

export function formatBytes(bytes = 0): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** index);
  return `${value >= 100 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`;
}

export function formatSpeed(bytesPerSecond = 0): string {
  return bytesPerSecond > 0 ? `${formatBytes(bytesPerSecond)}/s` : '';
}

export function taskMatchesFilter(job: Job, filter: TaskFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'active') return !['completed', 'failed', 'cancelled'].includes(job.status);
  return job.status === filter;
}

export function isActiveTask(job: Job): boolean {
  return !['completed', 'failed', 'cancelled'].includes(job.status);
}

export function canRetryTask(job: Job): boolean {
  return Boolean(job.canRetry) && ['failed', 'cancelled'].includes(job.status);
}

export function aggregateTaskMetrics(jobs: Job[]): { active: number; speedBytesPerSecond: number; downloadedBytes: number } {
  return jobs.reduce((metrics, job) => {
    const active = isActiveTask(job);
    metrics.active += active ? 1 : 0;
    metrics.speedBytesPerSecond += active ? job.speedBytesPerSecond ?? 0 : 0;
    metrics.downloadedBytes += job.downloadedBytes ?? 0;
    return metrics;
  }, { active: 0, speedBytesPerSecond: 0, downloadedBytes: 0 });
}
