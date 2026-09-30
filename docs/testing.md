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
8. 检查请求头和 Cookie 没有出现在设置文件中。
9. 下载完成后用 Quick Look、浏览器和 `ffprobe` 验证文件。

## Tauri 验证

```sh
pnpm tauri:dev
cargo tauri build --bundles app
```

公开发行前还必须运行：

```sh
pnpm release:package -- v0.1.0
```

确认 `release/v0.1.0/SHA256SUMS.txt` 校验通过，并使用 `scripts/verify-release.sh` 检查签名、架构、Homebrew 路径闭包、内置扩展和法律材料。对应源码归档必须包含主项目、yt-dlp 子模块、Homebrew 配方与收据、依赖许可证、下载的源码输入及 PyInstaller 构建工具源码；`PYTHON-DEPENDENCIES.json` 不应出现用户目录中的无关 Python 包。

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

如果 Cargo 在 macOS 启动即报 `libz3.4.15.dylib` 缺失，先通过本地代理更新或重装 Homebrew 的 `rust llvm z3`，确认动态库版本匹配，再重跑上述命令。本机还需要 Rust 1.88+，因为当前解析出的 Tauri 依赖中有包声明了该最低版本。这个错误发生在 rustc 启动阶段，不能用前端或 Python 检查代替。

## 已知限制

- 当前真实端到端验证使用本地短 HLS 源，自动测试覆盖直链分流和 MP4 规范化；代理出口、一次性签名地址、AES 密钥、DASH 票据和真实站点的权限仍需按目标站点做手工验收。
- 网络超时回归通过 yt-dlp 和网关参数测试覆盖：yt-dlp 请求有 30 秒 socket 超时、分片重试上限为 3，网关 curl 有 15 秒连接超时、30 秒总超时和 1 次轻量重试，并使用有界退避；自动测试验证首次 429 后可以恢复，真实代理出口仍需手工确认限流策略。
- 停滞保护依赖进度事件：90 秒写入停滞提示，180 秒取消并失败。它是有界保护，不代表代理一定恢复；真实 429 仍需更换出口、降低新任务并发或重新捕获签名地址。
- PNG 图片 HLS 自动测试已覆盖：150 分片并发成功、HTML/错误页失败、所有 future 等待时的取消和独立停滞超时、失败状态分类、ffmpeg 合并取消、字节/速度统计以及失败校验不发布最终文件。真实一次性签名地址仍需目标站点手工验收。
- PNG 包装 MPEG-TS 的回归测试需确认解析到 PNG `IEND` 后再寻找连续 188 字节 TS 包，最终 MP4 同时保留视频与音频。真实 TurboSPlayer 样本应抽查开头、中段和结尾分片，并通过代理完成连续分片封装验证。
- 当前已生成并验证 Intel `x86_64` `.app`，使用 ad-hoc 签名；Apple Developer ID 公证和 `arm64` 构建仍未完成。
