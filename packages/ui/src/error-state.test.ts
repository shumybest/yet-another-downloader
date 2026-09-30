import assert from 'node:assert/strict';
import test from 'node:test';
import { friendlyError } from './error-state.ts';

test('classifies common download failures and preserves raw details', () => {
  const cases = [
    ['curl: (35) LibreSSL SSL_connect: SSL_ERROR_SYSCALL', '安全连接失败'],
    ['HTTP Error 429: Too Many Requests', '请求过于频繁'],
    ['operation timed out after 30 seconds', '连接超时'],
    ['HTTP Error 403: Forbidden', '访问凭据已失效'],
    ['No space left on device', '磁盘空间不足'],
    ['Could not resolve host: media.example', '无法连接视频源'],
    ['Port 8765 is occupied by an outdated local engine', '本地引擎不可用'],
  ] as const;

  for (const [detail, title] of cases) {
    const result = friendlyError(detail);
    assert.equal(result.title, title);
    assert.equal(result.detail, detail);
    assert.ok(result.guidance.length > 0);
  }
});

test('uses a safe generic summary for an unknown failure', () => {
  assert.equal(friendlyError('unexpected decoder state').title, '下载失败');
});
