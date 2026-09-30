# Branding, Startup Recovery, and Extension Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a branded, self-recovering, extension-enabled, self-contained macOS yet another downloader application.

**Architecture:** Tauri starts the engine asynchronously and exposes state through commands; React renders startup/help flows; the Chrome service worker owns per-tab badge projection from session captures. Release scripts build and stage the extension and all runtime binaries as Tauri resources.

**Tech Stack:** React 18, TypeScript, Chrome Manifest V3, Rust 1.98, Tauri 1.8, Bash, PyInstaller, Tencent VOD Image Studio.

**Spec:** `docs/superpowers/specs/2026-09-29-branding-startup-extension-bundle-design.md`

## Global Constraints

- Preserve the dark-teal and acid-lime visual identity.
- Use Tencent VOD Image Studio for the source icon artwork.
- Keep deep links free of media URLs, cookies, headers, authorization values, and tokens.
- Never terminate an incompatible external listener on port 8765.
- Package the Python/yt-dlp sidecar, ffmpeg, ffprobe, Chrome extension, and icons inside the `.app`.
- Use `/usr/local/Caskroom/miniforge/base/envs/m3u8-bridge/bin/python` for Python packaging.

---

### Task 1: Product Icon Assets

**Files:**
- Create: `assets/branding/icon-source.png`
- Create: `apps/chrome-extension/public/icons/icon-{16,32,48,128}.png`
- Modify: `apps/chrome-extension/public/manifest.json`
- Modify: `src-tauri/tauri.conf.json`

**Interfaces:**
- Produces: Tauri icon set in `src-tauri/icons` and Chrome manifest icon paths.

- [x] Generate three transparent 1024x1024 VOD candidates after validating the compiled prompt with `--dry-run`.
- [x] Inspect candidates at 1024px, 128px, and 16px; select the cleanest silhouette and save it as `assets/branding/icon-source.png`.
- [x] Run `cargo tauri icon assets/branding/icon-source.png` and derive Chrome PNG sizes from the same source.
- [x] Add manifest `icons` and `action.default_icon`, then run the extension build and inspect emitted assets.

### Task 2: Asynchronous Engine Recovery

**Files:**
- Modify: `src-tauri/src/main.rs`
- Modify: `apps/desktop/src/main.tsx`
- Modify: `apps/desktop/src/main.css`

**Interfaces:**
- Produces: `EngineManager::begin_startup(AppHandle)`, `EngineStatus.state = starting`, and a desktop startup surface.

- [x] Add Rust tests proving a starting manager reports `starting`, retry succeeds after transient failures, and incompatible probes are not retried destructively.
- [x] Run `cargo test --manifest-path src-tauri/Cargo.toml` and confirm the new tests fail for missing startup state/retry helpers.
- [x] Implement background startup, three attempts, bounded backoff, and restart-lock coordination.
- [x] Run Rust tests and verify the setup callback returns without waiting for readiness.
- [x] Add desktop startup-state rendering and CSS, then run TypeScript/build checks.

### Task 3: Embedded Extension Installer

**Files:**
- Create: `scripts/stage-extension.sh`
- Modify: `src-tauri/src/main.rs`
- Modify: `src-tauri/tauri.conf.json`
- Modify: `apps/desktop/src/main.tsx`
- Modify: `apps/desktop/src/main.css`
- Modify: `package.json`

**Interfaces:**
- Produces: Tauri commands `prepare_chrome_extension() -> String`, `reveal_chrome_extension()`, and Help/About UI.

- [x] Add Rust tests for safe recursive resource copying and replacement of stale managed files.
- [x] Run Rust tests and confirm failure because the copy helper is absent.
- [x] Implement staging script, resource declaration, stable application-support extraction, and Finder reveal.
- [x] Add Help/About drawer with installation steps and actions.
- [x] Run staging, extension build, TypeScript, and desktop build checks.

### Task 4: Per-Tab Capture Badge

**Files:**
- Create: `apps/chrome-extension/src/badge.ts`
- Create: `apps/chrome-extension/src/badge.test.ts`
- Modify: `apps/chrome-extension/src/background.ts`

**Interfaces:**
- Produces: `formatBadgeCount(count: number): string` and `updateTabBadge(tabId: number, captures: Capture[]): Promise<void>`.

- [x] Add pure tests for zero, normal, boundary, and overflow badge text.
- [x] Run extension tests and confirm failure because `badge.ts` is absent.
- [x] Implement formatting and wire badge updates after capture insertion, navigation, removal, and service-worker activation.
- [x] Run extension and complete Node test suites.

### Task 5: Self-Contained Release And Verification

**Files:**
- Modify: `scripts/build-sidecar.sh`
- Modify: `docs/deployment.md`
- Modify: `docs/operation.md`
- Modify: `docs/testing.md`

**Interfaces:**
- Consumes: staged extension, icon assets, engine sidecar, ffmpeg, and ffprobe.
- Produces: `src-tauri/target/release/bundle/macos/yet another downloader.app`.

- [x] Run `pnpm test`, `pnpm exec tsc --noEmit`, and `pnpm build`.
- [x] Build the sidecar with `M3U8_BRIDGE_PYTHON=/usr/local/Caskroom/miniforge/base/envs/m3u8-bridge/bin/python scripts/build-sidecar.sh`.
- [x] Run Rust format, test, and check commands.
- [x] Run `cargo tauri build --bundles app` and enumerate required bundle files.
- [x] Cold-launch the app, wait up to 60 seconds for health, verify browser activation, terminate the parent, and assert the sidecar exits and port 8765 is released.
- [x] Document packaging, extension installation, startup recovery, and the exact verification procedure.
