import type { Capture, Job, MediaKind, MediaRendition } from '@m3u8-bridge/protocol';
import { canRetryTask, formatBytes, isActiveTask, type TaskFilter, taskMatchesFilter } from './task-state';
import { friendlyError } from './error-state';
import './styles.css';

export * from './task-state';
export * from './error-state';

export function AppShell({ children, compact = false, className = '', header }: {
  children: React.ReactNode;
  compact?: boolean;
  className?: string;
  header?: React.ReactNode;
}) {
  const classes = ['shell', compact ? 'shell-compact' : '', className].filter(Boolean).join(' ');
  return <main className={classes}>
    {header ?? <header className="topbar">
      <div className="brand-mark">MB</div>
      <div><strong>yet another downloader</strong><span>local media pipeline</span></div>
    </header>}
    {children}
  </main>;
}

export function ErrorDisclosure({ detail, className = '' }: { detail: string; className?: string }) {
  const error = friendlyError(detail);
  const copy = () => void navigator.clipboard?.writeText(error.detail);
  return <div className={`error-disclosure ${className}`.trim()} role="alert">
    <div className="error-summary">
      <div><strong>{error.title}</strong><span>{error.guidance}</span></div>
      <details>
        <summary>技术详情</summary>
        <div className="error-detail-toolbar"><button className="button button-link" onClick={copy}>复制日志</button></div>
        <pre>{error.detail}</pre>
      </details>
    </div>
  </div>;
}

export function ResourceList({ captures, onDownload }: {
  captures: Capture[];
  onDownload: (capture: Capture) => void;
}) {
  if (!captures.length) return <div className="empty">还没有捕获到媒体资源。打开视频页面并播放几秒。</div>;
  return <div className="resource-list">{captures.map((capture, index) => <article className="resource" key={`${capture.url}-${index}`}>
    <div className="resource-main">
      <div className={`pill pill-${capture.kind || 'direct'}`}>{kindLabel(capture.kind)}</div>
      <div className="resource-copy"><strong title={capture.title || '未命名视频'}>{capture.title || '未命名视频'}</strong><code title={mediaSourceLabel(capture.url)}>{mediaSourceLabel(capture.url)}</code><small>{mediaDetail(capture)}</small>{capture.mediaInfo?.renditions?.map(rendition => <small className="rendition-detail" key={rendition.id}>{renditionLabel(rendition)}</small>)}</div>
    </div>
    <button className="button button-primary" onClick={() => onDownload(capture)}>下载</button>
  </article>)}</div>;
}

function renditionLabel(rendition: MediaRendition): string {
  const parts: string[] = [];
  if (rendition.width && rendition.height) parts.push(`${rendition.width}x${rendition.height}`);
  if (rendition.bitrate) parts.push(rendition.bitrate >= 1_000_000 ? `${(rendition.bitrate / 1_000_000).toFixed(2)} Mbps` : `${Math.round(rendition.bitrate / 1_000)} Kbps`);
  if (rendition.videoCodec) parts.push(rendition.videoCodec);
  if (rendition.audioCodec) parts.push(rendition.audioCodec);
  return `码流 ${parts.join(' · ') || rendition.id}`;
}

function mediaDetail(capture: Capture): string {
  const info = capture.mediaInfo;
  const parts: string[] = [];
  if (info?.width && info.height) parts.push(`${info.width}x${info.height}`);
  if (info?.bitrate) parts.push(info.bitrate >= 1_000_000 ? `${(info.bitrate / 1_000_000).toFixed(2)} Mbps` : `${Math.round(info.bitrate / 1_000)} Kbps`);
  if (info?.duration) {
    const seconds = Math.round(info.duration);
    parts.push(`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`);
  }
  return parts.join(' · ') || '媒体信息待探测';
}

function mediaSourceLabel(url: string): string {
  try {
    const parsed = new URL(url);
    const source = `${parsed.host}${parsed.pathname}`;
    if (source.length <= 72) return source;
    return `${source.slice(0, 34)}...${source.slice(-34)}`;
  } catch {
    return url.length <= 72 ? url : `${url.slice(0, 34)}...${url.slice(-34)}`;
  }
}

function kindLabel(kind: MediaKind | undefined): string {
  return ({ hls: 'HLS', dash: 'DASH', direct: '直链' }[kind || 'direct']);
}

export function JobList({ jobs, filter = 'all', onCancel, onRetry, onDelete, onReveal }: {
  jobs: Job[];
  filter?: TaskFilter;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onDelete: (id: string) => void;
  onReveal: (path: string) => void;
}) {
  const visibleJobs = jobs.filter(job => taskMatchesFilter(job, filter));
  if (!visibleJobs.length) return <div className="empty">暂无符合条件的下载任务</div>;
  return <div className="job-list">{visibleJobs.map(job => <article className="job" key={job.id}>
    <div className="job-head"><div className="job-title"><span className={`pill pill-${job.kind || 'direct'}`}>{kindLabel(job.kind)}</span><strong>{job.title}</strong></div><span className={`status status-${job.status}`}>{statusLabel(job.status)}</span></div>
    <div className="progress"><i style={{ width: `${Math.max(0, Math.min(job.progress, 100))}%` }} /></div>
    <div className="job-meta"><span>{job.progress.toFixed(1)}%</span><span>{job.speed || `${job.downloadedFragments}${job.totalFragments ? `/${job.totalFragments}` : ''} 个分片`}</span><span>{formatBytes(job.downloadedBytes)}{job.totalBytes ? ` / ${formatBytes(job.totalBytes)}` : ''}</span></div>
    <div className="job-submeta"><span>第 {job.attempt || 1} 次尝试</span>{job.retryOf && <span>重试自 {job.retryOf.slice(0, 8)}</span>}{job.lastActivityAt && <span>最后活动 {new Date(job.lastActivityAt).toLocaleTimeString()}</span>}</div>
    {job.stallReason && <div className="warning">{job.stallReason}</div>}
    {job.outputPath && <div className="job-path"><code>{job.outputPath}</code><button className="button button-link" onClick={() => onReveal(job.outputPath!)}>在 Finder 中显示</button></div>}
    {job.error && <ErrorDisclosure detail={job.error} />}
    <div className="job-actions">
      {isActiveTask(job) && <button className="button button-ghost" onClick={() => onCancel(job.id)}>取消</button>}
      {canRetryTask(job) && <button className="button button-primary" onClick={() => onRetry(job.id)}>重新下载</button>}
      {!isActiveTask(job) && <button className="button button-ghost" onClick={() => onDelete(job.id)}>删除记录</button>}
    </div>
  </article>)}</div>;
}

function statusLabel(status: Job['status']): string {
  return ({ queued: '排队中', probing: '探测中', downloading: '下载中', muxing: '封装中', validating: '校验中', completed: '已完成', failed: '失败', cancelled: '已取消' })[status];
}

export function SectionTitle({ title, detail }: { title: string; detail?: string }) {
  return <div className="section-title"><h2>{title}</h2>{detail && <span>{detail}</span>}</div>;
}
