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

export function processingView(job: Job, now = Date.now()) {
  if (!['muxing', 'validating'].includes(job.status)) return null;
  const labels: Record<string, string> = { merging: '合并封装', transcoding: '转码为 H.264', scanning: '完整文件扫描', 'checking-head': '开头解码校验', 'checking-tail': '结尾解码校验' };
  const percent = typeof job.processingProgress === 'number' && Number.isFinite(job.processingProgress) ? Math.min(99.9, Math.max(0, job.processingProgress)) : null;
  const elapsed = Math.max(0, Math.floor((now - (job.processingStartedAt || now)) / 1000));
  const clock = (value: number) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`;
  return { percent, label: labels[job.processingStage || ''] || (job.status === 'muxing' ? '封装处理中' : '校验处理中'),
    detail: `${clock(job.processingSeconds || 0)}${job.processingDuration ? ` / ${clock(job.processingDuration)}` : ''}${job.processingSpeed ? ` · ${job.processingSpeed}` : ''} · 已用 ${clock(elapsed)}` };
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
