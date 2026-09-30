export const ENGINE_API_REVISION = 2;

export interface EngineHealthContract {
  ok: boolean;
  version?: string;
  apiRevision?: number;
  capabilities?: string[];
  ffmpeg?: string | null;
  ytDlp?: string | null;
}

export function assertCompatibleHealth(health: EngineHealthContract): void {
  if (!health.ok) throw new Error('本地下载引擎未就绪');
  if ((health.apiRevision ?? 0) < ENGINE_API_REVISION || !health.capabilities?.includes('jobs.delete')) {
    throw new Error('本地下载引擎接口版本过旧，请关闭旧引擎后重新启动桌面端');
  }
}
