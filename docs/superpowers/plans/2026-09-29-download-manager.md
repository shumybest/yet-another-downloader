# 下载管理与任务持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代理 HLS 分片长时间停滞，并把桌面端升级为带速度、历史和任务管理能力的本地下载器。

**Architecture:** Python 引擎以 SQLite 保存脱敏任务历史，内存继续保存当前任务所需的捕获凭据；任务创建时固定并发快照，运行中通过进度心跳和有限等待防止假死。React/Tauri 桌面端读取新的任务字段并提供筛选、重试、删除历史、清理完成记录和 Finder 定位操作。

**Tech Stack:** Python 3.13 standard library (`sqlite3`, `threading`), yt-dlp, curl, ffmpeg/ffprobe, TypeScript, React, Tauri 1.x, Node test runner。

**Spec:** `docs/superpowers/specs/2026-09-29-download-manager-design.md`

## Global Constraints

- 不发送 `SIGUSR1`、`SIGUSR2` 或其他未确认注册的 Unix 信号。
- 不主动取消用户当前保留的下载任务；新代码通过后续任务验证。
- SQLite 不存储 Cookie、Authorization、完整请求头或完整签名媒体 URL。
- 当前下载任务的分片并发在创建时固定；设置变化只对新任务生效。
- 现有 HLS、DASH、直链、MP4 规范化和扩展构建测试必须保持通过。
- 每个任务结束前必须继续执行视频流、时长和短时解码校验。

## File Map

- Create: `engine/m3u8_bridge/history.py` - SQLite schema、迁移和任务历史读写。
- Modify: `engine/m3u8_bridge/server.py` - 任务持久化、速度/心跳、恢复、重试和历史 API。
- Modify: `engine/m3u8_bridge/gateway.py` - 分片请求等待上限和减少嵌套重试。
- Modify: `packages/protocol/src/index.ts` - 任务管理 API 和任务展示字段。
- Modify: `apps/desktop/src/main.tsx` - 任务筛选、操作、持久化请求和 Finder command 调用。
- Modify: `packages/ui/src/index.tsx` - 速度、状态、历史任务操作组件。
- Modify: `packages/ui/src/styles.css`、`apps/desktop/src/main.css` - 下载器管理界面样式。
- Modify: `src-tauri/src/main.rs` - `reveal_path` command。
- Test: `tests/test_history.py`, `tests/test_server.py`, `tests/test_gateway.py` - Python 回归和 API 行为。
- Test: `packages/ui/src/task-state.test.ts` - 前端格式化、筛选和操作条件。
- Modify: `docs/architecture.md`, `docs/operation.md`, `docs/testing.md` - 新任务存储和操作手册。

### Task 1: SQLite History Store

**Files:**
- Create: `engine/m3u8_bridge/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- `HistoryStore(path: Path)`
- `HistoryStore.upsert(job: dict) -> None`
- `HistoryStore.load() -> list[dict]`
- `HistoryStore.delete(job_id: str) -> bool`
- `HistoryStore.clear_completed() -> int`
- `HistoryStore.mark_interrupted() -> int`

- [x] Write tests for schema initialization, upsert/load, active-job recovery, delete, and clear-completed.
- [x] Run the history tests and verify they pass.
- [x] Implement SQLite schema with only public job fields and `sourceFingerprint`, WAL mode, parameterized statements, and atomic upsert.
- [x] Implement `mark_interrupted()` to convert active statuses to failed with a fixed non-secret message.

### Task 2: Engine Persistence and Stall Protection

**Files:**
- Modify: `engine/m3u8_bridge/server.py`
- Modify: `engine/m3u8_bridge/gateway.py`
- Test: `tests/test_server.py`, `tests/test_gateway.py`

**Interfaces:**
- `Job` public fields include `downloadedBytes`, `totalBytes`, `lastActivityAt`, `stallReason`, `attempt`, `retryOf`, `canRetry`.
- `Engine.retry_job(job_id: str) -> dict`
- `Engine.delete_job(job_id: str) -> bool`
- `Engine.clear_completed() -> int`

- [x] Add tests for speed calculation, job persistence, retry availability, and gateway bounded retry flags.
- [x] Add `HistoryStore` to `Engine`, load records during initialization, and mark previous active jobs interrupted.
- [x] Persist sanitized public fields from `_update`; never pass `_capture` to SQLite.
- [x] Add byte counters and monotonic speed calculation to yt-dlp progress hooks; set `lastActivityAt` on progress and failure.
- [x] Add a daemon watchdog that marks a job stalled after 90 seconds and cancels it after 180 seconds without progress.
- [x] Add retry/delete/clear methods and API routes, preserving the original record and creating a linked retry record.
- [x] Retain bounded gateway waits and retry behavior.
- [x] Run all Python tests and verify they pass.

### Task 3: Shared Task Protocol and UI State

**Files:**
- Modify: `packages/protocol/src/index.ts`
- Create: `packages/ui/src/task-state.ts`
- Test: `packages/ui/src/task-state.test.ts`

**Interfaces:**
- `Job` includes the new progress and retry fields.
- `EngineClient.retryJob(id)`, `deleteJob(id)`, and `clearCompleted()` call the new API routes.
- `formatSpeed(bytesPerSecond)`, `formatBytes(bytes)`, `taskMatchesFilter(job, filter)` are pure functions.

- [x] Add TypeScript tests for byte/speed formatting, filter categories, and retry availability.
- [x] Extend the protocol and implement pure task-state helpers.
- [x] Add the three API client methods.
- [x] Run focused UI tests, then `pnpm exec tsc --noEmit`.

### Task 4: Desktop Download Manager UI

**Files:**
- Modify: `apps/desktop/src/main.tsx`
- Modify: `packages/ui/src/index.tsx`
- Modify: `packages/ui/src/styles.css`
- Modify: `apps/desktop/src/main.css`

- [x] Add pure helper coverage for selected filters and operation availability.
- [x] Replace the single job list with filter tabs and operations: cancel, retry, delete, clear completed, reveal path.
- [x] Render speed, byte progress, last activity/stall reason, attempt/retry relationship, and output path.
- [x] Mark concurrency setting as applying to new tasks only.
- [x] Run `pnpm test`, `pnpm exec tsc --noEmit`, and `pnpm build`.

### Task 5: Tauri Finder Command

**Files:**
- Modify: `src-tauri/src/main.rs`
- Modify: `apps/desktop/src/main.tsx`

- [x] Add a Rust command testable by compile: `reveal_path(path: String)`, reject empty/nonexistent paths, and invoke `open -R` without shell interpolation.
- [x] Register the command and call it from the desktop UI only for an existing local output path.
- [x] Run `cargo check` through direct Cargo and `pnpm exec tsc --noEmit`.

### Task 6: Documentation and End-to-End Verification

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/operation.md`
- Modify: `docs/testing.md`

- [x] Document the SQLite path, privacy boundary, retry semantics, interrupted-task recovery, and new UI operations.
- [x] Run the complete verification matrix:
  - `pnpm test`
  - `pnpm exec tsc --noEmit`
  - `pnpm build`
  - `PYTHONPATH=engine conda run --no-capture-output -n m3u8-bridge python -m unittest discover -s tests -v`
  - `PYTHONPATH=engine conda run --no-capture-output -n m3u8-bridge python -m py_compile engine/m3u8_bridge/*.py`
  - `git diff --check`
- [x] Read the live task state without mutating it and report the observed terminal state.
