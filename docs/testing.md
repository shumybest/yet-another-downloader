# 测试手册

本文验证 `yet another downloader` 桌面端、扩展和兼容性内核。

## 自动检查

在项目根目录执行：

```sh
pnpm exec tsc --noEmit
pnpm build
pnpm test
CONDA="${M3U8_BRIDGE_CONDA_BIN:-$(command -v conda)}"
PYTHONPATH=engine "$CONDA" run --no-capture-output -n m3u8-bridge \
  python -m unittest discover -s tests -v
"$CONDA" run --no-capture-output -n m3u8-bridge \
  python -m py_compile engine/m3u8_bridge/*.py
git diff --check
cargo fmt --check --manifest-path src-tauri/Cargo.toml
cargo test --manifest-path src-tauri/Cargo.toml
cargo check --manifest-path src-tauri/Cargo.toml
```

这些检查分别覆盖共享 TypeScript 类型、扩展悬浮层状态、桌面端构建、扩展构建、媒体类型捕获、Python 网关重写、下载分流、MP4 规范化和代码空白。

### 视频完整性回归

`tests/test_download_source.py` 使用保留域名测试网页识别、CDN 单轨回到原网页、去除跨域凭据和 Range、禁止网页 curl 降级；真实 FFmpeg 本地样本检查 `_run_job` 发布的 MP4 同时包含视频和音频。`tests/test_server.py` 检查纯音频输入在转码前明确失败且保留来源文件、最终合并路径优先于音频路径、残留分片不得成为输出。视频映射和最终校验保持强制。

真实站点验收须设置可用代理，分别测试 YouTube 网页手动提交和浏览器 CDN 捕获。确认输出视频轨、音频轨、时长与画面一致；短样本下载不代表已完成全长视频验收。测试日志、带签名的 URL 和视频文件不得提交到仓库。

### 悬浮控件浏览器回归

构建后运行真实 Chromium DOM 回归脚本（需自行安装 Playwright 及 Chromium；也可指定本地 Chrome）：

```sh
pnpm build:extension
node scripts/test-extension-overlay.mjs
```

脚本默认导入 `playwright`；不在项目依赖中安装时，可用 `M3U8_BRIDGE_PLAYWRIGHT_MODULE` 指定其 JS 入口的绝对路径，`M3U8_BRIDGE_CHROME_PATH` 指定 Chrome 可执行文件。可用 `M3U8_BRIDGE_OVERLAY_SCREENSHOT` 指定截图路径。浏览器运行在临时独立配置中，不修改用户现有 Chrome 实例。

覆盖：收起后新增 12 个资源、元数据更新和切换视频均保持折叠；资源计数更新；展开后可滚动且不遮挡整个视频；300px 窗口无横向溢出；下载和关闭仍可点击。测试使用 loopback 视频元素和模拟 Chrome 消息，不代替真实扩展 webRequest 嗅探验收。

## 引擎健康检查

启动 `scripts/run-engine.sh` 后执行：

```sh
curl http://127.0.0.1:8765/healthz
curl http://127.0.0.1:8765/api/session
```

健康响应应包含 `ok: true`、ffmpeg 路径和 yt-dlp 版本。`/api/session` 返回的令牌只在当前引擎进程内有效。

## 本地媒体端到端检查

用 ffmpeg 生成一个短 HLS 源，启动本地 HTTP 服务，再通过 `/api/jobs` 提交任务。HLS 外，再用一个本地 MP4 或 DASH manifest 手工提交捕获对象，验证直链/DASH 分流。统一验证以下结果：

- 任务状态从 `probing` 进入 `downloading`，最终为 `completed`。
- `outputPath` 指向非空 MP4。
- `downloadedBytes`、`totalBytes`、`speed` 和 `lastActivityAt` 在有进度事件时更新；修改设置中的并发后，当前任务的并发不改变。
- `ffprobe` 能识别 `video` stream 和大于零的 duration。
- `ffmpeg -v error -xerror -i output.mp4 -map 0:v:0 -map 0:a? -c copy -f null -` 全文件扫描返回 0。
- 开头 5 秒解码返回 0；时长大于 10 秒时，结尾 5 秒解码也返回 0。

本机已实际执行 HLS 网关场景：4 秒 H.264 HLS、4 个分片以并发 8 经网关下载后任务完成并生成可播放 MP4。另执行 150 个 PNG 分片的 8 并发压力场景，完整下载、逐片规范化、合并和校验约 3.8 秒完成；自动测试还覆盖非 H.264 输入转为 MP4。

## Chrome 手工验收

1. 构建扩展并在 `chrome://extensions` 加载 `apps/chrome-extension/dist`。
2. 打开带 HLS、DASH 或 MP4/WebM 播放器的页面，播放 3 到 5 秒。
3. 确认对应视频元素右上角出现浅蓝色媒体悬浮卡片，标题、类型和大小显示正确。
4. 在同一视频触发多个分辨率或码流，确认同一个悬浮区域内逐行列出全部资源，并尽量显示分辨率、码率和时长。
5. 依次移动到其他已捕获视频，确认悬浮区域切换到当前视频且不会持续叠加旧区域。
6. 点击资源行，确认状态变为“已提交下载任务”，桌面端出现任务并最终生成可播放 MP4。
7. 点击单条红色 `×`，确认该码流消失；点击面板顶部 `×`，确认当前视频的全部提示关闭。
8. 点击“收起”后继续播放、切换清晰度、切换视频和滚动页面，确认新增资源只增加计数而不展开；点击“展开”可查看全部保留资源。刷新页面恢复默认展开。
9. 检查请求头和 Cookie 没有出现在设置文件中。
10. 下载完成后用 Quick Look、浏览器和 `ffprobe` 验证文件。

## Tauri 验证

```sh
pnpm tauri:dev
cargo tauri build --bundles app
```

公开发行前还必须运行：

```sh
pnpm release:package -- v0.1.4
```

确认 `release/v0.1.4/SHA256SUMS.txt` 校验通过，并使用 `scripts/verify-release.sh` 检查签名、架构、Homebrew 路径闭包、内置扩展和法律材料。对应源码归档必须包含主项目、yt-dlp 子模块、Homebrew 配方与收据、依赖许可证、下载的源码输入及 PyInstaller 构建工具源码；`PYTHON-DEPENDENCIES.json` 不应出现用户目录中的无关 Python 包。

发布构建前需运行 `scripts/build-sidecar.sh`。构建后验证包内至少包含：

```text
Contents/MacOS/yet another downloader
Contents/MacOS/m3u8-bridge-engine
Contents/Resources/binaries/ffmpeg
Contents/Resources/binaries/ffprobe
Contents/Resources/binaries/lib/*.dylib
Contents/Resources/resources/chrome-extension/manifest.json
Contents/Resources/icon.icns
```

用 `otool -L` 遍历 ffmpeg、ffprobe 和 `binaries/lib`，非系统依赖只能使用 `@loader_path`，不得残留 `/usr/local`、`/opt/homebrew` 或 Cellar 绝对路径。随后直接执行包内 `ffmpeg -version` 和 `ffprobe -version`。

重复构建回归需要先运行一次 Cargo 构建，再重新执行 `scripts/build-sidecar.sh`，随后再次运行 `cargo test` 和 `cargo check`。第二次构建不得因 `target/*/binaries/lib` 中旧 dylib 的只读权限报 `Permission denied`。

桌面 UI 需要分别以 1120×780 和 740×560 验收：默认窗口的 `body.scrollHeight` 应等于 `body.clientHeight`，横向不得溢出；任务超过可见高度时只有 `.desktop-task-scroll` 滚动。顶部引擎、全局速率、活动任务、已下载数据应在同一状态区，设置只通过抽屉出现，同行操作按钮高度一致。错误默认只展示中文摘要，展开“技术详情”后可看到并复制原始内容。

热唤醒可在 Tauri 运行时用当前会话令牌调用：

```sh
token=$(curl -fsS http://127.0.0.1:8765/api/session | sed -E 's/.*"token"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
curl -fsS -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8765/api/app/activate
```

响应应为 `{"activated": true}`，最小化或隐藏的窗口应恢复并置前。发布包冷启动按部署手册检查 `CFBundleURLTypes` 后执行 `open 'm3u8bridge://download'`；确认应用从完全退出状态立即显示 Loading，随后引擎通过 `/healthz`，且返回的 `ffmpeg` 路径位于当前 `.app/Contents/Resources/binaries`。强制终止桌面进程后等待 sidecar 完成父进程检测和清理，确认 8765 不再被占用。

桌面端任务管理验收：创建或捕获任务后确认重启引擎能够保留历史；取消失败任务后点击“重新下载”会产生新的 `attempt`/`retryOf` 记录；删除记录和清理完成记录不会删除输出文件；对已存在输出文件点击 Finder 定位能够打开其所在目录。

手动创建任务验收：在桌面端点击“新建下载”，先提交空地址和非 HTTP(S) 地址，确认显示输入提示且不会创建任务；再提交带签名参数的媒体 URL 与自定义任务名称，确认原始 URL 未被重写、任务出现在列表中。无扩展名的媒体链接可显式指定 HLS、DASH 或视频直链；引擎不可用时表单应保留输入并显示技术详情。

菜单栏验收：关闭主窗口后确认进程和引擎仍在运行；左键点击菜单栏图标应恢复并置前窗口；创建活动任务后确认图标旁每秒更新合计下载速度，任务结束后速度文字消失；右键菜单中的状态行不可点击，“打开主窗口”恢复窗口，“退出 yet another downloader”才会终止应用及其管理的 sidecar，并释放 8765 端口。

GitHub Actions 使用锁文件做干净安装。修改 Node 依赖后应至少执行一次 `pnpm install --frozen-lockfile && pnpm typecheck`；Rust/Tauri 任务使用 `macos-latest`，避免绑定已经下线或长期无可用容量的旧 macOS Runner。

如果 Cargo 在 macOS 启动即报 `libz3.4.15.dylib` 缺失，先通过本地代理更新或重装 Homebrew 的 `rust llvm z3`，确认动态库版本匹配，再重跑上述命令。本机还需要 Rust 1.88+，因为当前解析出的 Tauri 依赖中有包声明了该最低版本。这个错误发生在 rustc 启动阶段，不能用前端或 Python 检查代替。

## 已知限制

- 当前真实端到端验证使用本地短 HLS 源，自动测试覆盖直链分流和 MP4 规范化；代理出口、一次性签名地址、AES 密钥、DASH 票据和真实站点的权限仍需按目标站点做手工验收。
- 网络超时回归通过 yt-dlp 和网关参数测试覆盖：yt-dlp 请求有 30 秒 socket 超时、分片重试上限为 3，网关 curl 有 15 秒连接超时、30 秒总超时和 1 次轻量重试，并使用有界退避；自动测试验证首次 429 后可以恢复，真实代理出口仍需手工确认限流策略。
- 停滞保护依赖进度事件：90 秒写入停滞提示，180 秒取消并失败。它是有界保护，不代表代理一定恢复；真实 429 仍需更换出口、降低新任务并发或重新捕获签名地址。
- PNG 图片 HLS 自动测试已覆盖：150 分片并发成功、HTML/错误页失败、所有 future 等待时的取消和独立停滞超时、失败状态分类、ffmpeg 合并取消、字节/速度统计以及失败校验不发布最终文件。真实一次性签名地址仍需目标站点手工验收。
- PNG 包装 MPEG-TS 的回归测试需确认解析到 PNG `IEND` 后再寻找连续 188 字节 TS 包，最终 MP4 同时保留视频与音频。真实 TurboSPlayer 样本应抽查开头、中段和结尾分片，并通过代理完成连续分片封装验证。
- 当前已生成并验证 Intel `x86_64` `.app`，使用 ad-hoc 签名；Apple Developer ID 公证和 `arm64` 构建仍未完成。

## 引擎启动回归

Rust 的 `engine_probe` 测试使用临时 loopback 端口模拟空闲端口、慢响应、HTTP 404 外部服务，以及返回 Content-Length 后保持连接的健康服务。慢响应应为等待状态，外部服务应为真实冲突，完整健康响应应立即通过。重启测试还确认等待旧监听端口释放，不会把尚未退出的旧进程误当作可复用引擎。

桌面端 `engine-startup.test.ts` 检查实际阶段映射与耗时显示。手动验收时确认：启动阶段逐项更新、失败保留详情、处理冲突后可重新检查、引擎提前退出可见、发布版日志可打开、启动中退出应用不遗留引擎。

## 代理路由与访问日志回归

媒体后处理回归：`tests/test_media_progress.py` 使用真实 FFmpeg 验证运行中进度回传，短时限模拟持续推进超过旧总时限、不推进仍被终止、失败保留原始下载且不发布输出、兼容编码只封装，以及直接调用 yt-dlp RetryManager 验证 `n` 关键字。长视频不再固定 900 秒停止；本轮未等待一整段超过 15 分钟的真实视频转码。

`PYTHONPATH=engine python3 -m unittest discover -s tests -p test_network_routing.py -v` 覆盖 HTTP/SOCKS5 代理仍由 HLS 网关使用、yt-dlp 显式直连本地网关、空代理不继承环境变量、外网 curl 不受 `NO_PROXY` 意外绕过。真实下载测试用临时端口的代理和中继，代理拒绝转发 loopback 请求，并使用真实 yt-dlp/FFmpeg 下载 HLS、封装和校验含视频与音频轨的 MP4；不使用用户端口或私有媒体。

日志测试确认成功的 GET 轮询和分片请求静默，失败响应、任务修改和协议错误仍可见。真实站点检查只验证代理取回清单及 yt-dlp 经本地中继解析成功，不代表整段视频已下载。

## 2026-10-21 回归记录

- `pnpm verify` 通过：35 个 TypeScript 测试、87 个 Python 测试、18 个 Rust 测试，公开树检查、类型检查和桌面/扩展构建均通过。
- 真实 Chrome 悬浮层 DOM 回归通过，并人工检查展开/收起截图；连续新增资源不会自动展开，展开列表限高且无横向溢出。
- 用户报告的 YouTube 视频通过代理，以默认格式策略和低清晰度策略分别下载前 8 秒样本；默认样本为 1920×1080、H.264/AAC MP4，时长 8.001 秒，音视频合并、引擎校验和全样本解码通过。未执行整段约 45 分钟视频下载，也未验证 Quick Look 原生界面。
- 本轮验证针对源码和扩展构建；未重新发布安装包。Rust 仍有上游 `block v0.1.6` 的未来兼容性警告，不影响本轮编译或测试。
