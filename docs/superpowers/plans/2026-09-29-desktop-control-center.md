# Desktop Control Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved full-width desktop download control center with friendly expandable errors, restartable engine controls, and extension-triggered hot/cold desktop activation.

**Architecture:** React owns presentation and polling, shared pure modules normalize task errors and aggregate metrics, Tauri owns engine lifecycle and native window activation, and the authenticated Python loopback API forwards hot-activation intent. A custom `m3u8bridge://` URL supplies credential-free cold launch for the packaged macOS app.

**Tech Stack:** React 18, TypeScript, CSS Grid, Tauri 1.8/Rust, Python 3.13 stdlib HTTP server, Chrome MV3, Node test runner, unittest.

**Spec:** `docs/superpowers/specs/2026-09-29-desktop-control-center-design.md`

## Global Constraints

- Keep the existing deep-teal and acid-lime visual identity shown in `docs/mockups/desktop-control-center-topbar-01.png`.
- The default 1120x780 window must not body-scroll; only the task list may scroll.
- Never place media URLs, cookies, headers, tokens, or signed query strings in a deep link or persisted diagnostic.
- Never kill an incompatible process that Tauri does not own.
- Existing staged `.gitmodules` and `vendor/yt-dlp` state must remain untouched; this unborn repository cannot receive isolated incremental commits safely.

---

### Task 1: Shared Presentation Models

**Files:**
- Create: `packages/ui/src/error-state.ts`
- Create: `packages/ui/src/error-state.test.ts`
- Modify: `packages/ui/src/task-state.ts`
- Modify: `packages/ui/src/task-state.test.ts`
- Modify: `packages/protocol/src/index.ts`
- Modify: `engine/m3u8_bridge/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `friendlyError(detail: string): { title: string; guidance: string; detail: string }`.
- Produces: `aggregateTaskMetrics(jobs: Job[]): { active: number; speedBytesPerSecond: number; downloadedBytes: number }`.
- Extends `Job` with optional `speedBytesPerSecond` populated from yt-dlp progress.

- [ ] Write failing tests for SSL, HTTP 429, timeout, authorization, disk, network, and unknown error summaries.
- [ ] Write failing tests for aggregate active count, byte totals, and numeric speed.
- [ ] Write a failing Python test proving progress exports numeric `speedBytesPerSecond`.
- [ ] Run the focused tests and confirm the missing interfaces fail.
- [ ] Implement the pure formatters and numeric progress field.
- [ ] Run the focused tests and TypeScript compiler.

### Task 2: Full-Width Desktop UI

**Files:**
- Modify: `apps/desktop/src/main.tsx`
- Modify: `apps/desktop/src/main.css`
- Modify: `packages/ui/src/index.tsx`
- Modify: `packages/ui/src/styles.css`

**Interfaces:**
- Consumes: `friendlyError` and `aggregateTaskMetrics` from Task 1.
- Produces: an `ErrorDisclosure` component with friendly summary, guidance, expandable raw detail, and copy action.
- Produces: a settings drawer controlled by one header button.

- [ ] Add component-state tests for collapsed error details and equal action variants where pure rendering state is available.
- [ ] Replace the hero and persistent settings block with the approved compact header, metric cluster, and settings drawer.
- [ ] Make the desktop shell a `100dvh` grid with `min-height: 0`; assign scrolling only to `.desktop-task-scroll` above the narrow breakpoint.
- [ ] Normalize all task and toolbar buttons to shared 34px/38px size tokens.
- [ ] Replace raw task/global error blocks with `ErrorDisclosure` while retaining verbatim details.
- [ ] Build desktop and verify 1120x780 plus 740x560 rendered layouts.

### Task 3: Restartable Engine Lifecycle

**Files:**
- Modify: `src-tauri/src/main.rs`
- Modify: `src-tauri/Cargo.toml`
- Modify: `apps/desktop/src/main.tsx`

**Interfaces:**
- Produces Tauri commands `engine_status() -> EngineStatus`, `restart_engine() -> EngineStatus`, and `open_engine_log() -> Result<(), String>`.
- `EngineStatus` contains `state`, `message`, and `managed`.

- [ ] Add Rust tests for state classification and refusal to restart an incompatible external listener.
- [ ] Move child ownership and last startup error into managed `EngineManager` state.
- [ ] Keep the UI alive when initial engine startup fails and expose the error through `engine_status`.
- [ ] Serialize restart, stop owned children, wait for port release, spawn, and wait for capability readiness.
- [ ] Redirect development engine output to `~/Library/Logs/m3u8-bridge/engine.log` and expose Finder/open access.
- [ ] Connect the header state and restart/log controls to Tauri commands, with web-preview fallbacks.
- [ ] Run Rust tests/check and manually kill/restart an owned engine through the UI.

### Task 4: Hot Window Activation

**Files:**
- Modify: `engine/m3u8_bridge/server.py`
- Modify: `packages/protocol/src/index.ts`
- Modify: `src-tauri/src/main.rs`
- Modify: `apps/chrome-extension/src/background.ts`
- Modify: `apps/chrome-extension/src/popup.tsx`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces authenticated `POST /api/app/activate -> { activated: boolean }`.
- Produces `EngineClient.activateApp()`.
- Tauri supplies `M3U8_BRIDGE_DESKTOP_PID`; the engine signals only that validated positive PID.

- [ ] Write Python tests for authorized activation, absent PID, and invalid PID behavior.
- [ ] Add a Tauri signal listener that restores, shows, and focuses the main window.
- [ ] Add the activation endpoint and protocol client method.
- [ ] After successful job creation, make popup and overlay downloads request activation without failing the already-created job if focus fails.
- [ ] Verify a minimized Tauri window is restored and focused after an extension download action.

### Task 5: Packaged Cold Launch

**Files:**
- Create: `src-tauri/Info.plist`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/src/main.rs`
- Modify: `apps/chrome-extension/src/background.ts`
- Modify: `apps/chrome-extension/src/overlay-state.test.ts`

**Interfaces:**
- Registers `m3u8bridge://download` through `tauri-plugin-deep-link` 0.1.2.
- Produces `submitWithDesktopLaunch(capture, launch, createJob)` with a bounded retry deadline.

- [ ] Write tests proving cold launch occurs only for engine-unavailable errors, retries are bounded, and no capture data enters the launch URL.
- [ ] Register the macOS URL scheme and deep-link listener; every event focuses the main window.
- [ ] Add extension cold-launch orchestration and a clear terminal error when launch/retry fails.
- [ ] Build the `.app`, inspect its `Info.plist`, and invoke `open 'm3u8bridge://download'` to verify launch/focus.

### Task 6: Documentation And Final QA

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/operation.md`
- Modify: `docs/testing.md`
- Modify: `README.md`

**Interfaces:**
- Documents the engine states, restart workflow, log location, custom protocol behavior, and Chrome first-launch confirmation.

- [ ] Update architecture and operator documentation without including credentials or signed URLs.
- [ ] Run Python, Node, TypeScript, Vite build, Rust formatting/tests/check, and Tauri application startup.
- [ ] Render-test 1120x780 and 740x560 for overflow, task scrolling, error disclosure, settings drawer, and restart controls.
- [ ] Verify hot focus in development and cold launch against the packaged `.app`.
- [ ] Record any macOS/Chrome confirmation limitation in the final result.
