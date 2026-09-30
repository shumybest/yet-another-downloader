# 部署手册

本文适用于 `yet another downloader`。为兼容旧版本，内部引擎名、环境变量、数据目录和 `m3u8bridge://` 协议保持不变。

## 环境要求

- macOS，当前工程已在 Intel `x86_64` 环境验证。
- Node.js、pnpm 10、Rust/Cargo 1.88+、Tauri CLI 1.x。
- Miniforge conda，Python 3.13；项目会使用 conda 环境 `m3u8-bridge`。
- `ffmpeg` 和 `ffprobe`，开发环境可执行 `brew install ffmpeg`。
- 如网络环境需要代理，请预先设置标准 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量；下面的 `127.0.0.1:7890` 仅为示例。

## 首次安装

在项目根目录执行：

```sh
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
git submodule update --init --recursive
pnpm install --registry=https://registry.npmjs.org/
scripts/bootstrap.sh
```

`vendor/yt-dlp` 固定在提交 `51bab8a0116f4d8004c315706d809782607d5847`。脚本会创建或复用 conda 环境 `m3u8-bridge`，并在其中安装该源码和 PyInstaller。项目默认输出到 `~/Downloads`，默认并发数为 8。

脚本不依赖 `conda` alias，也不需要先执行 `conda activate`。如果 GUI 启动环境没有完整 PATH，可显式指定 Miniforge：

```sh
M3U8_BRIDGE_CONDA_BIN=/usr/local/bin/conda \
M3U8_BRIDGE_CONDA_ENV=m3u8-bridge \
scripts/bootstrap.sh
```

## 启动桌面端

```sh
pnpm tauri:dev
```

Tauri 会启动本地 Python 引擎并打开桌面窗口。引擎健康检查地址为 `http://127.0.0.1:8765/healthz`。

如果只需要运行引擎：

```sh
scripts/run-engine.sh
```

如需绕过 conda 进行一次性诊断，可显式指定 Python：

```sh
M3U8_BRIDGE_PYTHON=/path/to/python \
M3U8_BRIDGE_PORT=8765 \
PYTHONPATH="engine:vendor/yt-dlp" \
scripts/run-engine.sh
```

## 构建 Chrome 扩展

```sh
pnpm build:extension
```

源码开发时，打开 Chrome 的 `chrome://extensions`，开启开发者模式，选择“加载已解压的扩展程序”，目录选择：

```text
apps/chrome-extension/dist
```

发布版不需要源码目录。打开桌面端顶部“帮助”，点击“准备扩展文件”，应用会将内置扩展释放到：

```text
~/Library/Application Support/m3u8-bridge/chrome-extension
```

随后点击“打开 Chrome 扩展页”，在 Chrome 开启开发者模式并加载上述目录。每次发布新版 App 后可再次点击“准备扩展文件”，旧的受管扩展文件会被完整替换。

桌面端运行后，在视频页面播放几秒，点击扩展图标即可看到当前页面捕获到的 m3u8。

## 设置与代理

桌面端设置页可修改输出目录、代理和分片并发。非敏感设置写入：

```text
~/Library/Application Support/m3u8-bridge/settings.json
```

Cookie、Authorization 和浏览器请求头不会写入这个文件。需要 HTTP 代理时填 `http://127.0.0.1:7890`；如果使用 SOCKS5，可填 `socks5h://127.0.0.1:7890`。

## 当前发布边界

开发模式已能启动 Tauri、引擎和扩展构建。发布机准备 sidecar：

```sh
scripts/build-sidecar.sh
cargo tauri build --bundles app
```

建议显式使用 Miniforge 环境中的 Python：

```sh
M3U8_BRIDGE_PYTHON=/usr/local/Caskroom/miniforge/base/envs/m3u8-bridge/bin/python \
  scripts/build-sidecar.sh
cargo tauri build --bundles app
```

脚本使用 PyInstaller 打包 Python engine 和 yt-dlp，复制 ffmpeg/ffprobe，并在 macOS 上递归收集所有非系统 Mach-O dylib、改写为包内 `@loader_path`。脚本会清理 `target/debug`、`target/release` 中旧的 Tauri 二进制资源副本，避免 Homebrew dylib 的只读权限导致重复构建失败。扩展生产构建和 `LICENSE`、`THIRD_PARTY_NOTICES.md`、yt-dlp Unlicense、FFmpeg GPLv3 文本会自动复制到 Tauri resources。当前 Intel 构建包含 92 个 ffmpeg 依赖库，不要求目标机器安装 Homebrew ffmpeg、Python 或 yt-dlp。

> **公开二进制发布门禁：** 当前 Homebrew FFmpeg 启用了 GPL 组件。上传 `.app`、`.dmg` 或 `.zip` 前，发布者必须完成 `THIRD_PARTY_NOTICES.md` 中列出的完整许可证、构建配置、动态库许可和对应源码义务。仅附带 MIT 或 GPL 文本并不充分。当前仓库 CI 不自动发布二进制。

无 Apple Developer ID 时可对本机发布副本做 ad-hoc 签名：

```sh
APP="src-tauri/target/release/bundle/macos/yet another downloader.app"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=1 "$APP"
```

ad-hoc 签名适合本机直接运行，不等同于 Developer ID 签名和 Apple notarization。向其他用户分发前仍需正式签名、公证，并分别构建/验收 `x86_64` 和 `arm64`。

发布后的 `.app` 在 `Info.plist` 中注册 `m3u8bridge` URL scheme。构建后必须检查并做冷启动验收：

```sh
APP="src-tauri/target/release/bundle/macos/yet another downloader.app"
/usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes' "$APP/Contents/Info.plist"
open "$APP"                    # 首次运行让 LaunchServices 注册应用
open 'm3u8bridge://download'   # 应恢复现有窗口或冷启动应用
```

Chrome 首次调用自定义协议可能要求用户确认打开外部应用，这是浏览器安全机制，不能也不应绕过。协议只传递 `download` 意图，不包含媒体 URL 或授权信息。

Rust、LLVM 和 Z3 由 Homebrew 管理。本机确认 `rustc`、`cargo` 来自 `/usr/local/bin` 的 Homebrew 安装；更新时需让 Homebrew 和 Cargo 同时走本地代理：

```sh
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
export ALL_PROXY=http://127.0.0.1:7890
export HOMEBREW_HTTP_PROXY=http://127.0.0.1:7890
export HOMEBREW_HTTPS_PROXY=http://127.0.0.1:7890
brew update
brew upgrade rust llvm z3
```
