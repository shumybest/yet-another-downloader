import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { EngineClient, type EngineSettings, type Job } from '@m3u8-bridge/protocol';
import {
  aggregateTaskMetrics,
  AppShell,
  ErrorDisclosure,
  formatBytes,
  formatSpeed,
  JobList,
  type TaskFilter,
} from '@m3u8-bridge/ui';
import './main.css';

type EngineState = 'starting' | 'online' | 'offline' | 'incompatible';
interface EngineStatus { state: EngineState; message: string; managed: boolean }
type TauriWindow = Window & { __TAURI__?: { invoke: <T>(command: string, args?: Record<string, unknown>) => Promise<T> } };

const DEFAULT_ENGINE: EngineStatus = { state: 'starting', message: '正在连接本地下载引擎', managed: false };

function DesktopApp() {
  const client = useMemo(() => new EngineClient(), []);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [settings, setSettings] = useState<EngineSettings | null>(null);
  const [engine, setEngine] = useState<EngineStatus>(DEFAULT_ENGINE);
  const [filter, setFilter] = useState<TaskFilter>('all');
  const [actionError, setActionError] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [extensionBusy, setExtensionBusy] = useState(false);
  const [extensionPath, setExtensionPath] = useState('');

  const tauri = (window as TauriWindow).__TAURI__;
  const refreshEngine = async () => {
    if (tauri) {
      setEngine(await tauri.invoke<EngineStatus>('engine_status'));
      return;
    }
    try {
      await client.health();
      setEngine({ state: 'online', message: '本地下载引擎运行正常', managed: false });
    } catch (error) {
      setEngine({ state: 'offline', message: errorMessage(error), managed: false });
    }
  };

  const refreshData = async () => {
    const [nextJobs, nextSettings] = await Promise.all([client.listJobs(), client.getSettings()]);
    setJobs(nextJobs);
    setSettings(nextSettings);
  };

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      await refreshEngine().catch(error => active && setEngine({ state: 'offline', message: errorMessage(error), managed: false }));
      try {
        const [nextJobs, nextSettings] = await Promise.all([client.listJobs(), client.getSettings()]);
        if (active) { setJobs(nextJobs); setSettings(nextSettings); }
      } catch {
        // Engine status already contains the actionable connectivity diagnosis.
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [client]);

  useEffect(() => {
    document.body.classList.add('desktop-body');
    return () => document.body.classList.remove('desktop-body');
  }, []);

  const save = async (patch: Partial<EngineSettings>) => {
    try {
      setActionError('');
      setSettings(await client.saveSettings(patch));
    } catch (error) {
      setActionError(errorMessage(error));
    }
  };

  const runAction = async (action: () => Promise<unknown>) => {
    setActionError('');
    try { await action(); await refreshData(); }
    catch (error) { setActionError(errorMessage(error)); }
  };

  const revealPath = async (path: string) => {
    if (!tauri) { setActionError('请在 Tauri 桌面端中使用 Finder 定位'); return; }
    await runAction(() => tauri.invoke('reveal_path', { path }));
  };

  const restartEngine = async () => {
    if (!tauri) { setActionError('浏览器预览模式不能重启引擎，请启动 Tauri 桌面端'); return; }
    setRestarting(true);
    setActionError('');
    setEngine({ state: 'starting', message: '正在重启本地下载引擎', managed: true });
    try {
      setEngine(await tauri.invoke<EngineStatus>('restart_engine'));
      await refreshData();
    } catch (error) {
      setActionError(errorMessage(error));
      await refreshEngine().catch(() => undefined);
    } finally {
      setRestarting(false);
    }
  };

  const openEngineLog = async () => {
    if (!tauri) { setActionError('浏览器预览模式不能打开本地日志'); return; }
    try { await tauri.invoke('open_engine_log'); }
    catch (error) { setActionError(errorMessage(error)); }
  };

  const prepareExtension = async (reveal = false) => {
    if (!tauri) { setActionError('请在 Tauri 桌面端中安装浏览器扩展'); return; }
    setExtensionBusy(true);
    setActionError('');
    try {
      const path = await tauri.invoke<string>('prepare_chrome_extension');
      setExtensionPath(path);
      if (reveal) await tauri.invoke('reveal_path', { path });
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setExtensionBusy(false);
    }
  };

  const openChromeExtensions = async () => {
    if (!tauri) { setActionError('请在 Chrome 地址栏中打开 chrome://extensions'); return; }
    try { await tauri.invoke('open_chrome_extensions'); }
    catch (error) { setActionError(errorMessage(error)); }
  };

  const counts = {
    all: jobs.length,
    active: jobs.filter(job => !['completed', 'failed', 'cancelled'].includes(job.status)).length,
    completed: jobs.filter(job => job.status === 'completed').length,
    failed: jobs.filter(job => job.status === 'failed').length,
    cancelled: jobs.filter(job => job.status === 'cancelled').length,
  };
  const metrics = aggregateTaskMetrics(jobs);
  const visibleError = actionError || (engine.state === 'offline' || engine.state === 'incompatible' ? engine.message : '');

  const header = <header className="control-header">
    <div className="control-brand"><div className="brand-mark"><img src="/app-icon.png" alt="" /></div><div><strong>yet another downloader</strong><span>下载控制台</span></div></div>
    <div className="header-metrics" aria-label="下载概览">
      <Metric label="全局速率" value={formatSpeed(metrics.speedBytesPerSecond) || '0 B/s'} live={metrics.active > 0} />
      <Metric label="活动任务" value={String(metrics.active)} />
      <Metric label="已下载" value={formatBytes(metrics.downloadedBytes)} />
    </div>
    <div className="engine-control">
      <div className={`engine-state engine-${engine.state}`}><i /><span><b>{engineLabel(engine.state)}</b><small>{engine.managed ? '桌面端管理' : engine.state === 'online' ? '外部进程' : '需要处理'}</small></span></div>
      {engine.state !== 'online' && <button className="button button-primary" disabled={restarting || engine.state === 'incompatible'} onClick={() => void restartEngine()}>{restarting ? '重启中' : '重启引擎'}</button>}
      <button className="button button-ghost" onClick={() => void openEngineLog()}>日志</button>
      <button className="button button-ghost help-button" onClick={() => setHelpOpen(true)} aria-label="打开帮助">帮助</button>
      <button className="button button-ghost settings-button" onClick={() => setSettingsOpen(true)} aria-label="打开设置">设置</button>
    </div>
  </header>;

  return <AppShell className="desktop-shell" header={header}>
    {engine.state === 'starting' ? <StartupSurface message={engine.message} /> : <>
    <section className="workspace-intro">
      <div><p className="eyebrow">LOCAL MEDIA PIPELINE</p><h1>下载任务</h1></div>
      <p>{engine.message}</p>
    </section>
    <section className="task-workspace">
      <div className="task-toolbar">
        <nav className="filter-tabs" aria-label="任务筛选">{(['all', 'active', 'completed', 'failed', 'cancelled'] as TaskFilter[]).map(value => <button key={value} className={filter === value ? 'selected' : ''} onClick={() => setFilter(value)}>{filterLabel(value)} <b>{counts[value]}</b></button>)}</nav>
        <button className="button button-ghost" disabled={!counts.completed} onClick={() => void runAction(() => client.clearCompleted())}>清理已完成</button>
      </div>
      {visibleError && <ErrorDisclosure detail={visibleError} className="global-error" />}
      <div className="desktop-task-scroll">
        <JobList jobs={jobs} filter={filter} onCancel={id => void runAction(() => client.cancelJob(id))} onRetry={id => void runAction(() => client.retryJob(id))} onDelete={id => void runAction(() => client.deleteJob(id))} onReveal={path => void revealPath(path)} />
      </div>
    </section>
    </>}
    {settingsOpen && <SettingsDrawer settings={settings} onChange={setSettings} onSave={save} onClose={() => setSettingsOpen(false)} />}
    {helpOpen && <HelpDrawer extensionPath={extensionPath} busy={extensionBusy} onPrepare={prepareExtension} onOpenChrome={openChromeExtensions} onClose={() => setHelpOpen(false)} />}
  </AppShell>;
}

function StartupSurface({ message }: { message: string }) {
  return <section className="startup-surface" aria-live="polite" aria-busy="true">
    <div className="startup-orbit"><img src="/app-icon.png" alt="" /><i /><i /><i /></div>
    <p className="eyebrow">LOCAL ENGINE RECOVERY</p>
    <h1>正在准备下载引擎</h1>
    <p>{message}。首次启动需要解压本地组件，应用会自动重试，无需重复操作。</p>
    <div className="startup-progress"><span /></div>
  </section>;
}

function Metric({ label, value, live = false }: { label: string; value: string; live?: boolean }) {
  return <div className="header-metric"><span>{label}</span><strong className={live ? 'metric-live' : ''}>{value}</strong></div>;
}

function SettingsDrawer({ settings, onChange, onSave, onClose }: {
  settings: EngineSettings | null;
  onChange: (settings: EngineSettings) => void;
  onSave: (patch: Partial<EngineSettings>) => Promise<void>;
  onClose: () => void;
}) {
  return <div className="drawer-layer" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <aside className="settings-drawer" aria-label="下载设置">
      <header><div><p className="eyebrow">PREFERENCES</p><h2>下载设置</h2></div><button className="drawer-close" onClick={onClose} aria-label="关闭设置">×</button></header>
      {!settings ? <div className="empty">引擎连接后可编辑设置</div> : <div className="settings-form">
        <label>输出目录<input value={settings.outputDir} onChange={event => onChange({ ...settings, outputDir: event.target.value })} onBlur={() => void onSave({ outputDir: settings.outputDir })} /></label>
        <label>代理<input value={settings.proxy} placeholder="http://127.0.0.1:7890" onChange={event => onChange({ ...settings, proxy: event.target.value })} onBlur={() => void onSave({ proxy: settings.proxy })} /></label>
        <label>分片并发<input type="number" min="1" max="16" value={settings.concurrency} onChange={event => onChange({ ...settings, concurrency: Number(event.target.value) })} onBlur={() => void onSave({ concurrency: settings.concurrency })} /><small>范围 1-16，仅对新任务生效。</small></label>
      </div>}
    </aside>
  </div>;
}

function HelpDrawer({ extensionPath, busy, onPrepare, onOpenChrome, onClose }: {
  extensionPath: string;
  busy: boolean;
  onPrepare: (reveal?: boolean) => Promise<void>;
  onOpenChrome: () => Promise<void>;
  onClose: () => void;
}) {
  return <div className="drawer-layer" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <aside className="settings-drawer help-drawer" aria-label="帮助与浏览器扩展">
      <header><div><p className="eyebrow">HELP & EXTENSION</p><h2>连接 Chrome</h2></div><button className="drawer-close" onClick={onClose} aria-label="关闭帮助">×</button></header>
      <div className="extension-intro"><img src="/app-icon.png" alt="" /><div><strong>yet another downloader capture</strong><p>在网页中识别 HLS、DASH、MP4 等媒体并发送到桌面端。</p></div></div>
      <ol className="install-steps">
        <li><b>1</b><span>点击“准备扩展文件”，应用会把内置扩展释放到稳定目录。</span></li>
        <li><b>2</b><span>打开 Chrome 扩展管理页，开启右上角“开发者模式”。</span></li>
        <li><b>3</b><span>选择“加载已解压的扩展程序”，然后选择下方目录。</span></li>
      </ol>
      <div className="extension-actions">
        <button className="button button-primary" disabled={busy} onClick={() => void onPrepare(false)}>{busy ? '准备中…' : '准备扩展文件'}</button>
        <button className="button button-ghost" onClick={() => void onOpenChrome()}>打开 Chrome 扩展页</button>
        <button className="button button-ghost" disabled={!extensionPath || busy} onClick={() => void onPrepare(true)}>在 Finder 中显示</button>
      </div>
      <div className="extension-path"><span>加载目录</span><code>{extensionPath || '~/Library/Application Support/m3u8-bridge/chrome-extension'}</code></div>
      <footer><span>版本 0.1.1</span><span>本地处理，不上传捕获凭据</span></footer>
    </aside>
  </div>;
}

function engineLabel(state: EngineState): string {
  return ({ starting: '引擎启动中', online: '引擎在线', offline: '引擎离线', incompatible: '端口冲突' })[state];
}

function errorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message === 'Load failed' || message === 'Failed to fetch' ? '无法连接本地下载引擎，请检查引擎状态后重试' : message;
}

function filterLabel(filter: TaskFilter): string {
  return ({ all: '全部', active: '下载中', completed: '已完成', failed: '失败', cancelled: '已取消' })[filter];
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><DesktopApp /></React.StrictMode>);
