# 架构说明

## 目标

yet another downloader 将浏览器发现的 HLS、MPEG-DASH 和直链视频资源交给本地下载引擎，生成经过媒体检查的 MP4。桌面端是任务控制面，Chrome 扩展是资源捕获面，Python 引擎是下载数据面。

```text
Chrome MV3 extension
  webRequest -> Media Capture -> loopback API
                                      |
Tauri React UI <----------------------+
                                      v
                             Python local engine
                                      |
                         HLS gateway / yt-dlp + proxy
                                      |
                         yt-dlp DASH/direct + ffmpeg
                                      |
                              ffprobe/decode check
```

## 组件边界

- `apps/chrome-extension` 捕获 HLS、DASH 和常见直链视频响应、请求头、Cookie、页面信息，并把任务提交到桌面端；常见分片会过滤掉。`content.ts` 通过 Shadow DOM 将脱敏媒体卡片定位到对应视频元素右上角，并尽力读取 HLS/DASH 主清单中的码率、分辨率、时长和编码；后台校验并存储媒体信息，下载时再由后台取回完整捕获对象。Service worker 将每个标签页的去重资源数投影到工具栏角标，并在导航、关闭和 worker 重启时同步。
- `packages/capture-core` 包含 URL/MIME 类型判断、请求头筛选和去重指纹。它是独立重写，不复制 Cat-Catch GPL-3.0 源码。
- `packages/protocol` 定义 `Capture`、`Job`、`EngineSettings` 和本地 API 客户端，两个前端目标共用。
- `packages/ui` 提供共享 React 组件、错误归类和任务指标聚合。桌面端采用固定高度控制台：引擎状态、全局速率、活动任务和已下载字节集中在顶部，任务列表独立滚动，设置由临时抽屉承载。
- `engine/m3u8_bridge/gateway.py` 通过 curl 使用 HTTP 或 SOCKS 代理获取远程清单和分片，重写相对 URL、嵌套清单、`EXT-X-KEY`/`EXT-X-MAP` URI，并对临时 HTTP 失败有限重试；连接和总等待均有上限。
- `engine/m3u8_bridge/server.py` 管理任务线程、媒体类型分流、yt-dlp 参数、直链 fallback、MP4 规范化、并发度和成品验证。Cookie 和授权请求头只存在任务内存中。
- `engine/m3u8_bridge/history.py` 使用标准库 SQLite 持久化脱敏任务元数据，默认位于 `~/Library/Application Support/m3u8-bridge/history.sqlite3`。数据库不保存原始 URL、Cookie、Authorization 或完整请求头，只保存 URL 的 SHA-256 指纹。
- `src-tauri` 在开发模式启动 Python 引擎，在发布模式启动 `m3u8-bridge-engine` sidecar。setup 只创建后台启动线程，不等待最长 60 秒的 PyInstaller 解包，因此窗口能先显示 Loading；启动最多尝试 3 次。窗口关闭时隐藏控制台并保留下载；应用真正退出时才回收自管进程。引擎还会监视桌面父进程，异常退出后自动停止，避免孤儿 sidecar 占用 8765。发布包同时内置 Chrome 扩展与 ffmpeg/ffprobe 的非系统动态库。

## 本地协议

- `GET /healthz`：运行时检查，不要求令牌。
- `GET /api/session`：返回当前进程内令牌。
- `GET /api/jobs`、`GET /api/jobs/{id}`：查询任务。
- `POST /api/captures`：登记捕获元数据。
- `POST /api/jobs`：提交 `capture` 或 `captureId`，支持 `outputDir`、`proxy`、`concurrency`。
- `POST /api/jobs/{id}/cancel`：取消任务。
- `POST /api/jobs/{id}/retry`：基于仍在内存中的原始捕获创建新的尝试记录；引擎重启后必须重新捕获资源。
- `DELETE /api/jobs/{id}`：删除已结束任务的历史记录，不删除视频文件。
- `POST /api/jobs/clear-completed`：删除所有已完成历史记录，不删除视频文件。
- `POST /api/app/activate`：向 Tauri 注入的桌面 PID 发送本地激活信号；无有效 PID 时安全返回 `activated: false`。
- `GET/POST /api/settings`：读取或保存非敏感设置。

服务只绑定 `127.0.0.1:8765`。前端先读取 `/api/session`，后续请求携带 `Authorization: Bearer <token>`。HLS 网关地址只对 HLS 当前任务有效，任务结束后立即删除内存映射。

## 引擎生命周期与桌面唤醒

Tauri 将引擎归类为 `starting`、`online`、`offline` 或 `incompatible`，并记录进程是否由当前桌面实例管理。初次启动失败不会关闭 UI；用户可在顶部查看友好错误、展开原始日志并重启自管引擎。不兼容进程占用 8765 时不会被自动终止。

浏览器提交成功后调用已认证的 `/api/app/activate`，Python 只向 `M3U8_BRIDGE_DESKTOP_PID` 指向的正整数 PID 发送 `SIGUSR1`，Tauri 收到后恢复、显示并置前主窗口。引擎不可用时，扩展只打开 `m3u8bridge://download` 表达启动意图，并在 60 秒内有限重试，以覆盖 PyInstaller sidecar 首次解包；深链接中不包含捕获 URL、Cookie、请求头或令牌。macOS 协议声明位于 `src-tauri/Info.plist`。

## 任务生命周期与停滞保护

任务创建时复制输出目录、代理和分片并发；运行中修改设置不会改变当前任务。需要变更并发时，应取消当前任务并点击“重新下载”，新任务会以当前设置启动。

每次 yt-dlp 或图片分片的真实字节/分片增长都会更新内存进度；SQLite 进度快照最多约每 0.5 秒提交一次，状态切换和终态立即提交，避免高并发下载线程被数据库写入串行化。DASH 等分离音视频轨会按下载阶段累计计数，不会因第二轨从零开始而误判停滞。图片分片只维持并发窗口数量，不一次性创建全部 future；调度器使用短轮询同时观察取消和自身停滞期限，每个上游 curl 与 ffmpeg 子进程也有独立超时和取消收尾。90 秒无进度会显示可能停滞提示，180 秒无进度会取消外部下载并将任务标记为失败。失败/取消任务保留原记录，重试会创建 `retryOf` 指向父任务的新记录。

引擎启动时会把数据库中上一次遗留的活动任务标记为失败，提示“引擎重启时任务中断，请重新捕获资源后重试”。因为签名地址和凭据只在内存中，历史记录不能在重启后自动重试。

## 下载路径

HLS 使用本地网关和 yt-dlp 原生分片下载，DASH 与直链视频直接交给 yt-dlp，并传递浏览器请求头和代理。直链在 yt-dlp 失败时使用可取消 curl 拉取后交给 ffmpeg。所有任务先写入输出目录中的隐藏任务临时目录；H.264 仅在 Quick Look 兼容像素格式下直接保留，HEVC 还要求 `hvc1` 标签，否则转为 H.264/AAC。成品依次执行 ffprobe、全文件数据包扫描、开头解码和长视频结尾解码，全部成功后才原子发布；同名文件自动编号。探测到 PNG 分片时，下载器会区分纯图片 HLS 与在完整 PNG 后包装 MPEG-TS 的媒体分片；后者提取真实 TS 并保留原始视频和音频。

`scripts/build-sidecar.sh` 通过 `engine/sidecar_entry.py` 用 PyInstaller 打包 engine/yt-dlp，并复制 ffmpeg/ffprobe。macOS 构建随后使用 `scripts/bundle_macos_dylibs.py` 递归收集 Homebrew ffmpeg 的非系统依赖并改写为包内相对路径。`scripts/stage-extension.sh` 将扩展生产构建放入 Tauri resources，桌面端命令再把它释放到用户 Application Support。发布机仍需分别构建 x86_64 和 arm64，完成正式签名与安装验收。
