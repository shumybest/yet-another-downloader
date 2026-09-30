# yet another downloader

<p align="center">
  <img src="assets/branding/icon-source.png" width="144" alt="yet another downloader icon" />
</p>

<p align="center">
  A local-first macOS media downloader with a Tauri desktop app, Chrome capture extension, and Python/yt-dlp/FFmpeg engine.
</p>

[![CI](https://github.com/shumybest/yet-another-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/shumybest/yet-another-downloader/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What it does

- Detects HLS, MPEG-DASH, MP4, WebM, MOV, FLV, MPEG, OGV, and 3GP resources requested by a browser tab.
- Shows available renditions, resolution, bitrate, duration, codec, and estimated size when the source exposes that information.
- Downloads through a configurable proxy with bounded retries, cancellation, stall detection, and concurrent HLS fragment fetching.
- Normalizes output to a playable MP4 when stream copying is not compatible with common macOS players or Quick Look.
- Keeps download history locally and never persists captured cookies, authorization headers, or full signed media URLs.
- Bundles a Chrome extension installation flow into the desktop app.

The project is currently macOS-focused. The latest verified release build is Intel `x86_64`; Apple Silicon, Developer ID signing, and notarization still require separate release validation.

## Architecture

```text
Chrome extension
  -> authenticated loopback API on 127.0.0.1:8765
  -> Python download engine and HLS gateway
  -> yt-dlp + FFmpeg/ffprobe
  -> validated MP4 in the selected output directory

Tauri desktop app
  -> engine lifecycle, settings, history, logs, and native window activation
```

See [the architecture document](docs/architecture.md) for trust boundaries and data flow.

## Prerequisites

- macOS
- Node.js 22.6 or newer and pnpm 10
- Rust 1.88 or newer and Tauri CLI 1.x
- Miniforge with Python 3.13
- FFmpeg and ffprobe for development

## Development setup

```sh
git clone --recurse-submodules https://github.com/shumybest/yet-another-downloader.git
cd yet-another-downloader
corepack enable
pnpm install --frozen-lockfile
scripts/bootstrap.sh
pnpm tauri:dev
```

If dependencies must use a proxy, set standard proxy environment variables before running the commands. For example:

```sh
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
```

The application itself starts with proxying disabled. A proxy can be configured in Settings when the target media requires one. Existing installations continue to use their saved setting.

## Chrome extension

Run `pnpm build:extension`, open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select `apps/chrome-extension/dist`.

Packaged desktop builds also contain the extension. Open **Help**, select **Prepare extension files**, and follow the in-app installation steps.

## Verification

```sh
pnpm verify
```

The command checks the public tree, types, Node tests, Python tests, Rust formatting/tests/checks, and production web builds. Platform-specific packaging is documented in [docs/deployment.md](docs/deployment.md).

## Local data and privacy

- The engine listens only on loopback and protects mutating APIs with a process-local bearer token.
- Captured request headers and signed URLs stay in memory for the lifetime of a task.
- History stores redacted metadata and URL hashes, not full URLs or credentials.
- Existing compatibility data remains under `~/Library/Application Support/m3u8-bridge`.
- The `m3u8bridge://download` deep link contains only launch intent, never a media URL or credential.

Report security issues privately as described in [SECURITY.md](SECURITY.md). Never paste cookies, authorization headers, private videos, or signed URLs into a public issue.

## Responsible use

Use this software only for media you own or are authorized to download. It is not designed to bypass DRM, paywalls, authentication, access controls, service rate limits, or copyright restrictions. You are responsible for applicable law and website terms.

## Documentation

- [Operation guide](docs/operation.md)
- [Deployment and packaging](docs/deployment.md)
- [Testing guide](docs/testing.md)
- [Architecture](docs/architecture.md)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)

## AI-assisted development

This project has been substantially developed with AI coding assistance. Repository rules for humans and coding agents are documented in [AGENTS.md](AGENTS.md). Every contribution, AI-assisted or not, must be reviewed, tested, licensed, and submitted under the contributor's responsibility.

## License

Original project source is licensed under the [MIT License](LICENSE). Third-party projects and bundled binaries retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). In particular, an FFmpeg build with GPL components cannot be redistributed under MIT alone.
