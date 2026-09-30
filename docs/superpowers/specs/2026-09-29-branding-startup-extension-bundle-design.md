# Branding, Startup Recovery, and Extension Bundle Design

## Goal

Ship a self-contained macOS application with a recognizable yet another downloader icon, a non-blocking and recoverable engine startup experience, an embedded Chrome extension installation flow, per-tab media-count badges, and release verification proving every runtime dependency is inside the app bundle.

## Visual Identity

The icon uses the existing dark-teal and acid-lime product palette. Its silhouette combines a compact bridge or stream ribbon with a play triangle, has no text, and remains recognizable at 16px. Tencent VOD Image Studio produces three 1024x1024 transparent candidates; the strongest candidate is normalized into the Tauri/macOS icon set and Chrome 16/32/48/128 PNG assets.

## Engine Startup

Tauri setup must return immediately so the desktop shell is visible while the PyInstaller sidecar performs its measured cold start. `EngineManager` owns an explicit `starting` flag and starts the engine on a background worker. Startup performs up to three bounded attempts with short backoff, preserving the existing 15-second debug and 60-second release readiness windows. An incompatible listener on port 8765 is reported and never terminated.

The desktop displays a blocking startup surface only while the initial state is `starting`. The surface explains that the local engine is being prepared and keeps polling Tauri status. Online state reveals the task console; exhausted retries reveal the detailed error, engine log action, and manual restart action.

## Extension Installation

The extension production build is copied into `src-tauri/resources/chrome-extension` before release packaging and declared as a Tauri resource. A Tauri command copies the embedded directory to `~/Library/Application Support/m3u8-bridge/chrome-extension`, replacing only files managed by this application, and returns the stable path. A second command reveals that path in Finder.

The desktop Help/About drawer includes product information, a "准备扩展文件" action, a "打开扩展目录" action, a Chrome extensions-page action, and concise numbered instructions for enabling developer mode and choosing "加载已解压的扩展程序". Chrome internal URLs cannot be launched through a normal macOS URL opener reliably, so the UI copies `chrome://extensions` and opens Chrome when direct navigation is unavailable.

## Chrome Badge

The extension service worker derives each tab badge from unique captures stored in `chrome.storage.session`. Badge text is empty at zero, decimal from 1 through 99, and `99+` above 99. It updates after capture insertion, tab navigation/removal, session storage changes, and service-worker activation. Badge color uses the product acid-lime with dark-teal text where supported.

## Packaging And Security

The release bundle contains the desktop executable, PyInstaller/yt-dlp engine sidecar, ffmpeg, ffprobe, embedded Chrome extension, and icon assets. Deep links remain intent-only and must never include media URLs, cookies, headers, authorization values, or tokens. The app must not kill incompatible external processes on port 8765.

## Acceptance

- VOD source asset and generated macOS/Chrome sizes exist and render without transparent-padding or corruption issues.
- The window appears before the engine is ready, shows a loading state, and automatically reaches online when the sidecar becomes healthy.
- Failed automatic recovery exposes restart and log controls.
- The embedded extension can be installed from the stable application-support path without accessing the source checkout.
- Toolbar badges represent unique captures for the active tab and survive service-worker restart.
- Unit, TypeScript, frontend build, Rust format/test/check, Tauri app build, bundle-content, cold-start, activation, and orphan-cleanup checks pass.
