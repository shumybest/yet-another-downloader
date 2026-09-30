export interface FriendlyError {
  title: string;
  guidance: string;
  detail: string;
}

const RULES: Array<{ pattern: RegExp; title: string; guidance: string }> = [
  { pattern: /(?:local engine|本地下载引擎|引擎未运行|port 8765|端口 8765|did not become ready)/i, title: '本地引擎不可用', guidance: '请尝试重启引擎；端口冲突时先关闭旧版引擎进程。' },
  { pattern: /(?:ssl_|ssl\s|tls|certificate)/i, title: '安全连接失败', guidance: '请检查代理连接，或稍后重试该任务。' },
  { pattern: /(?:\b429\b|too many requests|rate.?limit)/i, title: '请求过于频繁', guidance: '服务端正在限流，请稍后重试或降低分片并发。' },
  { pattern: /(?:timed?\s*out|timeout|长时间无进度)/i, title: '连接超时', guidance: '视频源或代理响应过慢，请检查网络后重试。' },
  { pattern: /(?:\b401\b|\b403\b|forbidden|unauthorized|cookie|signature|token)/i, title: '访问凭据已失效', guidance: '请回到浏览器刷新页面并重新捕获资源。' },
  { pattern: /(?:no space left|disk full|磁盘空间)/i, title: '磁盘空间不足', guidance: '请释放输出磁盘空间或更换下载目录。' },
  { pattern: /(?:could not resolve|connection refused|could not connect|network|curl:)/i, title: '无法连接视频源', guidance: '请检查代理、网络和视频链接是否仍然有效。' },
];

export function friendlyError(detail: string): FriendlyError {
  const normalized = detail.trim() || 'Unknown error';
  const matched = RULES.find(rule => rule.pattern.test(normalized));
  return {
    title: matched?.title ?? '下载失败',
    guidance: matched?.guidance ?? '请展开技术详情检查原因，然后重试任务。',
    detail: normalized,
  };
}
