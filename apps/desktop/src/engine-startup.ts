export type EngineState = 'starting' | 'online' | 'offline' | 'incompatible';
export interface StartupProgress {
  stage: string;
  detail: string;
  attempt: number;
  elapsedMs: number;
  ytDlp?: string | null;
}
export interface EngineStatus { state: EngineState; message: string; managed: boolean; progress?: StartupProgress }

export const STARTUP_STEPS = [
  { stage: 'checking', label: '检查本地服务' },
  { stage: 'preparing', label: '准备 Python 组件' },
  { stage: 'launching', label: '启动引擎进程' },
  { stage: 'initializing', label: '恢复设置与记录' },
  { stage: 'ytdlp', label: '载入 yt-dlp' },
  { stage: 'healthcheck', label: '验证本地 API' },
] as const;

export function startupStepState(stage: string, stepIndex: number): 'complete' | 'current' | 'waiting' {
  if (stage === 'ready') return 'complete';
  const current = Math.max(0, STARTUP_STEPS.findIndex(step => step.stage === stage));
  return stepIndex < current ? 'complete' : stepIndex === current ? 'current' : 'waiting';
}

export function startupElapsed(elapsedMs = 0): string {
  const seconds = Math.floor(Math.max(0, elapsedMs) / 1000);
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}
