export const DESKTOP_LAUNCH_URL = 'm3u8bridge://download';

export interface LaunchRetryOptions {
  timeoutMs?: number;
  intervalMs?: number;
  now?: () => number;
  sleep?: (milliseconds: number) => Promise<void>;
}

export function isEngineUnavailable(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /failed to fetch|load failed|networkerror|local engine unavailable|本地下载引擎不可用/i.test(message);
}

export async function submitWithDesktopLaunch<T>(
  createJob: () => Promise<T>,
  launch: (url: string) => Promise<unknown>,
  options: LaunchRetryOptions = {},
): Promise<T> {
  try {
    return await createJob();
  } catch (error) {
    if (!isEngineUnavailable(error)) throw error;
  }

  await launch(DESKTOP_LAUNCH_URL);
  const timeoutMs = options.timeoutMs ?? 60_000;
  const intervalMs = options.intervalMs ?? 500;
  const now = options.now ?? Date.now;
  const sleep = options.sleep ?? ((milliseconds: number) => new Promise(resolve => setTimeout(resolve, milliseconds)));
  const deadline = now() + timeoutMs;
  let lastError: unknown;

  while (now() < deadline) {
    await sleep(intervalMs);
    try {
      return await createJob();
    } catch (error) {
      if (!isEngineUnavailable(error)) throw error;
      lastError = error;
    }
  }

  throw new Error(`桌面端启动超时，请手动打开 yet another downloader 后重试。${lastError ? ` ${String(lastError)}` : ''}`);
}
