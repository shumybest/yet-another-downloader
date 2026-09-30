# 多格式媒体捕获与下载 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture HLS, MPEG-DASH, and common direct video responses in Chrome and download them through a type-aware local pipeline with playable MP4 validation.

**Architecture:** Keep the HLS gateway for playlist rewriting and browser credentials. Route DASH and direct media URLs through yt-dlp with captured headers and proxy, then normalize and validate output with ffmpeg/ffprobe. Share a `MediaKind` classification between the extension and local API.

**Tech Stack:** TypeScript, Chrome MV3 `webRequest`, React, Python standard-library HTTP engine, vendored yt-dlp, ffmpeg/ffprobe, Tauri 1.x.

**Spec:** `docs/superpowers/specs/2026-09-28-multiformat-media-design.md`

## Global Constraints

- Preserve HLS gateway behavior and the current local bearer-token API.
- Use Miniforge `conda run`, not interactive `conda activate`.
- Keep proxy and captured credentials in memory; never write them to logs or settings.
- Capture media responses, not arbitrary HTML, and filter common streaming segments.
- A job is complete only after video-stream, duration, and short decode validation.

### Task 1: Shared Media Classification

**Files:**
- Modify: `packages/protocol/src/index.ts`
- Modify: `packages/capture-core/src/index.ts`
- Test: `packages/capture-core/src/index.test.ts`

- [x] Add `MediaKind = 'hls' | 'dash' | 'direct'` and `Capture.kind/contentType/contentLength`.
- [x] Add failing tests for MIME and extension detection, segment filtering, and title stripping.
- [x] Implement `classifyMedia(url, contentType): MediaKind | null`, `isMediaUrl`, and stable labels.
- [x] Run the capture-core test and then the full TypeScript checks.

### Task 2: Chrome Network Capture and Popup

**Files:**
- Modify: `apps/chrome-extension/src/background.ts`
- Modify: `apps/chrome-extension/src/popup.tsx`
- Modify: `apps/chrome-extension/public/manifest.json`
- Modify: `packages/ui/src/index.tsx`
- Modify: `packages/ui/src/styles.css`

- [x] Extend response capture from HLS-only to classified media responses and retain relevant headers.
- [x] Add deduplication that treats media kind as part of the capture identity.
- [x] Add UI resource labels and generic empty-state/help text.
- [x] Build the extension and inspect the generated manifest.

### Task 3: Engine Download Routing and Output Normalization

**Files:**
- Modify: `engine/m3u8_bridge/server.py`
- Modify: `engine/m3u8_bridge/gateway.py`
- Test: `tests/test_gateway.py`
- Create: `tests/test_server.py`

- [x] Add failing tests for HLS gateway routing, DASH/direct yt-dlp options, headers/proxy propagation, and safe output naming.
- [x] Route only HLS through the HLS gateway; pass direct/DASH URLs to yt-dlp with captured headers and proxy.
- [x] Add direct-download fallback through curl for generic media URLs.
- [x] Normalize non-MP4 or incompatible outputs with ffmpeg and validate with ffprobe plus decode check.
- [x] Preserve cancellation, retries, concurrency bounds, and credential redaction.
- [x] Run Python unittest tests in the Miniforge environment.

### Task 4: Documentation and Regression Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/operation.md`
- Modify: `docs/testing.md`

- [x] Document supported media kinds, segment filtering, download routing, and MP4 normalization.
- [x] Add troubleshooting for direct media, DASH, and codec conversion failures.
- [x] Run frontend tests/builds, Python tests, `cargo fmt --check`, debug/release checks, and Tauri dev health verification.
