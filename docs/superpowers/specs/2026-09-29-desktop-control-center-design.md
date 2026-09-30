# Desktop Control Center Design

## Scope

This change turns the desktop surface from a vertically stacked landing page into a compact download control center. It also adds explicit engine lifecycle controls and lets a Chrome extension download action activate or cold-start the desktop app.

The existing visual language remains: dark teal surfaces, lime primary actions, compact technical metadata, and the existing typography. No download-engine behavior or capture classification is changed.

## Desktop Layout

At desktop widths, the window is a fixed-height application shell rather than a document page:

- A compact 64px header contains brand, aggregate task activity, engine state, and engine controls.
- A short overview row replaces the oversized marketing hero.
- The main workspace is a full-width task area. There is no persistent right rail.
- Engine state, live aggregate speed, active-task count, and downloaded bytes form a lightweight status cluster in the header without enclosing cards.
- Settings are opened from one header button in a temporary drawer, then dismissed back to the task-focused view.
- The task list is the primary independently scrollable region. Header and filters remain visible.
- `min-height: 0`, constrained grid rows, and bounded overflow prevent accidental body scrolling at the configured 1120x780 window size.
- Below the desktop breakpoint, the layout becomes one column and falls back to normal page scrolling so narrow windows remain usable.

Buttons use shared size tokens: 34px compact controls and 38px primary controls. Every action group aligns controls to the same height; emphasis comes from color and fill, not different physical dimensions.

## Error Presentation

Errors are normalized into two layers:

- A concise Chinese summary identifies the category and next action, for example proxy/TLS failure, rate limiting, authorization expiry, disk failure, timeout, or engine unavailability.
- The original engine message remains available in a collapsed `details` disclosure with a copy button. Raw text wraps and has a bounded internal scroll area.

Task errors and global action errors use the same formatter and visual component. Raw URLs and authorization values remain subject to the engine's existing redaction rules.

## Engine Lifecycle

The Tauri layer becomes the owner of engine lifecycle state and exposes commands for:

- current state: `starting`, `online`, `offline`, or `incompatible`;
- whether the process is owned by this desktop instance;
- starting or restarting the engine;
- revealing the local engine log.

Startup remains capability-gated. A spawned engine is not considered online until `/healthz` reports the current API revision and required capabilities. Restart terminates an owned child, waits for port release, starts a new process, and waits for readiness. If another incompatible process owns port 8765, the UI reports that conflict instead of claiming success or killing an unrelated process.

The desktop UI polls both engine health and task data. When the engine fails, the header exposes a prominent restart action while retaining detailed diagnostics. A successful restart refreshes settings and jobs without reloading the webview.

## Browser-to-Desktop Activation

Two activation paths are used:

1. Hot activation: after the extension successfully creates a job, it calls authenticated `POST /api/app/activate`. The Python engine sends a local activation signal to the Tauri process ID supplied at engine startup. Tauri restores, shows, and focuses the main window.
2. Cold activation: if no engine is reachable, the extension opens `m3u8bridge://download`. The packaged app registers this URL scheme, starts, and focuses its main window. The extension retries task submission for a short bounded interval after requesting launch.

The extension never places captured URLs, cookies, headers, or tokens in the custom URL. The URL only expresses the intent to open the app. Chrome may show its standard external-application confirmation on first use. macOS protocol registration is validated against a built `.app`; development mode validates hot activation and the focus handler separately.

## Components And Interfaces

- `apps/desktop`: full-width control-center layout, settings drawer, engine state model, retry/restart interactions, error presentation.
- `packages/ui`: uniform button sizing, job error disclosure, bounded task-list layout.
- `packages/protocol`: engine status and activation methods plus structured API errors.
- `src-tauri`: engine lifecycle state, restart/status/log commands, window activation handler, and custom URL listener.
- `engine/m3u8_bridge/server.py`: authenticated activation endpoint and desktop PID signaling only; no UI responsibilities.
- `apps/chrome-extension`: activate after successful submission; cold-launch and bounded retry when the engine is unavailable.

## Failure Handling

- Restart requests are serialized so repeated clicks cannot spawn parallel engines.
- A failed restart leaves a durable diagnostic message and an actionable retry control.
- An occupied incompatible port is never killed automatically.
- Activation failure does not cancel a successfully created download job.
- Cold-launch retries have a hard deadline and end with an explicit instruction to open the app manually.
- The engine log is available from the desktop UI, while credentials and signed query strings remain redacted.

## Testing

- Unit tests cover error classification, engine-state transitions, activation retry decisions, and consistent button/action rendering state.
- Python tests cover activation authorization, invalid/stale desktop PIDs, and safe failure behavior.
- Rust tests cover health compatibility and restart-state decisions.
- Integration tests cover engine termination followed by desktop restart, `/api/app/activate`, and task refresh.
- Rendered QA checks the default 1120x780 viewport, the minimum 740x560 viewport, task-list scrolling, expanded error details, equal button dimensions, offline restart behavior, and window focus from the extension.
- Packaged-app QA verifies the `m3u8bridge://` URL scheme because macOS does not fully register it in ordinary `tauri dev` mode.

## Acceptance Criteria

- No body scrollbar appears at the default desktop window size; only the task list scrolls when needed.
- Narrow windows remain usable without clipped controls.
- Peer action buttons have equal height and predictable emphasis.
- Friendly error summaries are visible without exposing long raw logs; full logs remain accessible and copyable.
- A stopped owned engine can be restarted from the UI and returns to `online` only after a successful capability check.
- Extension download actions focus an existing desktop window.
- When the packaged app is closed, an extension download action can request a cold launch and then submit the task without embedding media credentials in the deep link.
