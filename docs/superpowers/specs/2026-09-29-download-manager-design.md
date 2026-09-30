# 下载管理与任务持久化设计

## 目标

把当前“内存中的一次性下载任务”升级为可诊断、可重试、可保留历史的本地下载管理器，同时修复 HLS 分片请求在代理异常或修改并发后长时间停留在某个分片的问题。

## 当前问题与证据

- 当前任务 `150/1564` 长时间没有 `updatedAt` 变化，`speed` 为空。
- Python 进程 CPU 很低，但存在 8 个并行 `curl` 子进程，正在通过代理请求 Google Drive 分片。
- `concurrency` 在 `create_job()` 时复制到 yt-dlp，运行中的任务不会读取后续设置变化，因此修改桌面设置不会动态改变当前任务。
- `Engine.jobs` 只存在于 Python 进程内存，引擎重启后任务和历史全部消失。
- 现有网关和 yt-dlp 均有重试，异常时形成嵌套等待；虽然每个 curl 有上限，但任务层没有活动心跳、停滞状态或可重试记录。

## 设计决策

### 1. SQLite 作为唯一历史存储

使用 Python 标准库 `sqlite3`，数据库位置为：

```text
~/Library/Application Support/m3u8-bridge/history.sqlite3
```

数据库使用 WAL 模式和参数化 SQL。存储任务状态、进度、速度、输出路径、错误和时间戳，不存储 Cookie、Authorization、完整请求头或完整签名媒体 URL。任务当前执行所需的捕获对象仍只存在内存中。

应用重启时：

- `queued`、`probing`、`downloading`、`muxing`、`validating` 任务统一标记为 `failed`。
- 错误为“引擎重启时任务中断，请重新捕获资源后重试”。
- 已完成、已失败、已取消记录继续保留。

### 2. 任务生命周期

```text
queued -> probing -> downloading -> muxing -> validating -> completed
   |          |            |           |          |
   +----------+------------+-----------+----------+-> failed
                         cancel -> cancelled
```

每个任务新增：

- `downloadedBytes`、`totalBytes`：用于速度和进度展示。
- `lastActivityAt`：最后一次收到分片或下载器进度事件的时间。
- `speed`：由 yt-dlp 事件速度或相邻字节样本计算。
- `attempt`、`retryOf`：标识重试关系。
- `canRetry`：当前进程仍保留捕获对象时为真。

任务创建时固定 `concurrency` 快照。设置页面明确标注“仅对新任务生效”。对当前任务修改并发的操作是“取消并按当前设置重试”，避免试图热修改 yt-dlp 内部线程池。

### 3. 卡死防护

- 网关使用较短的连接/传输上限，避免代理连接无限等待。
- yt-dlp 只保留有限分片重试，避免网关和 yt-dlp 进行长时间嵌套重试。
- `Engine` 在进度回调中更新 `lastActivityAt` 和速度。
- 后台监视器每 5 秒检查活动任务；超过 90 秒无活动时写入 `stallReason`，先将 UI 标记为“可能停滞”。超过 180 秒仍无活动，设置取消事件并让任务进入 `failed`，错误为“分片请求长时间无响应”。
- 网关为每个上游请求启动独立的 curl 进程组；取消或超时会只终止该子进程组，监视器不向 Python 主进程或其他用户进程发送信号。

### 4. API

保留现有 bearer token。

```text
GET    /api/jobs
GET    /api/jobs/{id}
POST   /api/jobs
POST   /api/jobs/{id}/cancel
POST   /api/jobs/{id}/retry
DELETE /api/jobs/{id}
POST   /api/jobs/clear-completed
GET    /api/settings
POST   /api/settings
```

删除历史默认只删除数据库记录，不删除视频文件。输出文件删除必须由单独显式操作完成，避免误删用户文件；本期桌面端提供“在 Finder 中显示”，不直接删除输出文件。

重试规则：

- 当前进程仍有 `_capture` 时，使用当前设置创建新任务。
- 引擎重启后没有凭据和签名 URL，历史记录 `canRetry=false`；UI 显示“请从扩展重新捕获”。
- 重试不会修改原记录，创建新记录并通过 `retryOf` 关联。

### 5. 桌面端

桌面端增加：

- 全部/下载中/已完成/失败/已取消筛选。
- 速度、已下载量、总量、最后活动时间和失败原因。
- 当前任务：取消、取消并重试、在 Finder 中显示。
- 历史任务：重新下载、删除记录。
- 批量清理已完成记录。
- 设置中的并发字段改名为“新任务分片并发”，旁边提示不影响正在运行的任务。

打开 Finder 使用 Tauri command 调用 macOS `open -R`，路径必须是本地路径且通过 `PathBuf` 传递，不拼接 shell 字符串。

## 安全边界

- SQLite 不持久化 Cookie、Authorization、User-Agent、Referer、Origin 或完整签名 URL。
- API 返回的历史记录不包含 `_capture` 和任何请求头。
- 错误信息继续通过 URL 脱敏函数处理。
- 本地数据库只绑定当前用户的 Application Support 目录；引擎仍只监听 `127.0.0.1`。

## 测试策略

- Python 单元测试覆盖 SQLite 初始化、活跃任务恢复、速度样本、停滞判定、重试和删除。
- API 测试覆盖 `retry`、`DELETE`、`clear-completed` 和历史返回字段。
- TypeScript 测试覆盖任务筛选、速度格式化和状态按钮规则。
- 构建和现有 HLS/DASH/直链测试必须继续通过。
- 真实当前任务只做只读观察；不向进程发送信号，不自动取消用户任务。
