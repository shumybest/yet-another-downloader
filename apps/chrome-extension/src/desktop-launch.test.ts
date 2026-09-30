import assert from 'node:assert/strict';
import test from 'node:test';
import { DESKTOP_LAUNCH_URL, submitWithDesktopLaunch } from './desktop-launch.ts';

test('launches desktop only for an unavailable engine and never exposes capture data', async () => {
  let attempts = 0;
  const launchUrls: string[] = [];
  let clock = 0;
  const result = await submitWithDesktopLaunch(
    async () => {
      attempts += 1;
      if (attempts < 3) throw new TypeError('Failed to fetch');
      return 'job-id';
    },
    async url => { launchUrls.push(url); },
    { timeoutMs: 1000, intervalMs: 100, now: () => clock, sleep: async milliseconds => { clock += milliseconds; } },
  );

  assert.equal(result, 'job-id');
  assert.deepEqual(launchUrls, [DESKTOP_LAUNCH_URL]);
  assert.equal(DESKTOP_LAUNCH_URL, 'm3u8bridge://download');
});

test('does not launch for a server-side job error', async () => {
  let launched = false;
  await assert.rejects(
    submitWithDesktopLaunch(async () => { throw new Error('403 expired token'); }, async () => { launched = true; }),
    /403 expired token/,
  );
  assert.equal(launched, false);
});

test('stops retrying at the configured deadline', async () => {
  let attempts = 0;
  let clock = 0;
  await assert.rejects(
    submitWithDesktopLaunch(
      async () => { attempts += 1; throw new TypeError('Failed to fetch'); },
      async () => undefined,
      { timeoutMs: 250, intervalMs: 100, now: () => clock, sleep: async milliseconds => { clock += milliseconds; } },
    ),
    /启动超时/,
  );
  assert.equal(attempts, 4);
});
