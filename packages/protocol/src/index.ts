import { assertCompatibleHealth } from './compatibility';
export { assertCompatibleHealth } from './compatibility';

export type JobStatus =
  | 'queued'
  | 'probing'
  | 'downloading'
  | 'muxing'
  | 'validating'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type HeaderMap = Record<string, string>;
export type MediaKind = 'hls' | 'dash' | 'direct';

export interface MediaRendition {
  id: string;
  url?: string;
  width?: number;
  height?: number;
  bitrate?: number;
  videoCodec?: string;
  audioCodec?: string;
}

export interface MediaInfo {
  width?: number;
  height?: number;
  duration?: number;
  bitrate?: number;
  videoCodec?: string;
  audioCodec?: string;
  renditions?: MediaRendition[];
}

export interface Capture {
  id?: string;
  url: string;
  pageUrl?: string;
  title?: string;
  tabId?: number;
  headers?: HeaderMap;
  cookie?: string;
  kind?: MediaKind;
  contentType?: string;
  contentLength?: number;
  mediaInfo?: MediaInfo;
  capturedAt?: number;
}

export interface JobOptions {
  outputDir?: string;
  filename?: string;
  proxy?: string;
  concurrency?: number;
}

export interface CreateJobRequest extends JobOptions {
  captureId?: string;
  capture?: Capture;
}

export interface Job {
  id: string;
  status: JobStatus;
  title: string;
  url: string;
  kind?: MediaKind;
  outputPath?: string;
  progress: number;
  downloadedFragments: number;
  totalFragments?: number;
  downloadedBytes?: number;
  totalBytes?: number;
  speed?: string;
  speedBytesPerSecond?: number;
  error?: string;
  lastActivityAt?: number;
  stallReason?: string;
  attempt?: number;
  retryOf?: string;
  canRetry?: boolean;
  createdAt: number;
  updatedAt: number;
}

export interface EngineSettings {
  outputDir: string;
  proxy: string;
  concurrency: number;
  ffmpegPath?: string;
  pythonPath?: string;
}

export interface HealthResponse {
  ok: boolean;
  version: string;
  apiRevision: number;
  capabilities: string[];
  ffmpeg: string | null;
  ytDlp: string | null;
}

export class EngineClient {
  private tokenPromise?: Promise<string>;
  private compatibilityPromise?: Promise<HealthResponse>;

  constructor(public readonly baseUrl = 'http://127.0.0.1:8765') {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    await this.ensureCompatible();
    const token = await this.getToken();
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(init?.headers ?? {}) },
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${await response.text()}`);
    }
    return response.json() as Promise<T>;
  }

  private ensureCompatible(): Promise<HealthResponse> {
    this.compatibilityPromise ??= fetch(`${this.baseUrl}/healthz`, { cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error(`本地下载引擎不可用 (${response.status})`);
      const health = await response.json() as HealthResponse;
      assertCompatibleHealth(health);
      return health;
    }).catch(error => {
      this.compatibilityPromise = undefined;
      throw error;
    });
    return this.compatibilityPromise;
  }

  private getToken(): Promise<string> {
    this.tokenPromise ??= fetch(`${this.baseUrl}/api/session`).then(async response => {
      if (!response.ok) throw new Error(`Local engine unavailable (${response.status})`);
      const result = await response.json() as { token: string };
      return result.token;
    }).catch(error => {
      this.tokenPromise = undefined;
      throw error;
    });
    return this.tokenPromise;
  }

  health() { return this.ensureCompatible(); }
  listJobs() { return this.request<Job[]>('/api/jobs'); }
  getSettings() { return this.request<EngineSettings>('/api/settings'); }
  saveSettings(settings: Partial<EngineSettings>) {
    return this.request<EngineSettings>('/api/settings', { method: 'POST', body: JSON.stringify(settings) });
  }
  createJob(request: CreateJobRequest) {
    return this.request<Job>('/api/jobs', { method: 'POST', body: JSON.stringify(request) });
  }
  cancelJob(id: string) {
    return this.request<Job>(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
  }
  retryJob(id: string) {
    return this.request<Job>(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' });
  }
  deleteJob(id: string) {
    return this.request<{ deleted: boolean }>(`/api/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }
  clearCompleted() {
    return this.request<{ deleted: number }>('/api/jobs/clear-completed', { method: 'POST' });
  }
  activateApp() {
    return this.request<{ activated: boolean }>('/api/app/activate', { method: 'POST' });
  }
  capture(capture: Capture) {
    return this.request<Capture>('/api/captures', { method: 'POST', body: JSON.stringify(capture) });
  }
}
