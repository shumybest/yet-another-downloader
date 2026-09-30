# Open Source Readiness Implementation Plan (Superseded)

> Status: superseded historical record. Do not use its MIT-only release decisions for current builds. The project was subsequently relicensed under GPL-3.0-or-later for bundled GPL binary releases.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Migrate the latest implementation into a clean canonical Git repository and make it safe, documented, licensed, reproducible, and CI-ready for public GitHub publication.

**Architecture:** Preserve both old directories as immutable recovery sources, recreate the canonical repository at its existing path from reviewed source files, and initialize an orphan public history. Keep compatibility-sensitive runtime identifiers while replacing organization-specific public identity and adding repository governance, policy, compliance, CI, and automated public-tree checks.

**Tech Stack:** Tauri 1/Rust, React/TypeScript/Vite/pnpm, Python 3.13, yt-dlp git submodule, ffmpeg/ffprobe, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-30-open-source-readiness-design.md`

## Global Constraints

- Canonical path remains the `yet-another-downloader` checkout.
- GitHub remote is `https://github.com/shumybest/yet-another-downloader.git`; do not push.
- New public history must not contain the old private draft commit or its author email.
- Preserve `m3u8bridge://`, port `8765`, `M3U8_BRIDGE_*`, internal package names, sidecar name, and existing Application Support paths.
- Exclude credentials, private media URLs, local state, build output, binaries, and personal absolute paths.
- Keep the original code under MIT and clearly disclose third-party licenses and FFmpeg binary-distribution obligations.

---

### Task 1: Create The Canonical Clean Repository

**Files:**
- Preserve: timestamped pre-open-source repository backup outside the checkout
- Create: `.git`
- Create: deprecation marker in the detached source directory

**Interfaces:**
- Consumes: latest source directory and old valid Git repository.
- Produces: a clean canonical working tree with a fresh `main` branch and configured origin.

- [x] Move the old canonical repository to a timestamped backup without deleting it.
- [x] Copy reviewed source files from the latest implementation, excluding `.git`, caches, build output, generated binaries, staged extension output, and the uninitialized submodule directory.
- [x] Initialize a new Git repository on `main`, configure `origin`, and initialize yt-dlp at the pinned commit.
- [x] Add a deprecation marker to the detached source directory pointing to the canonical repository and backup.
- [x] Verify the canonical path, remote, branch, submodule commit, and absence of inherited history.

### Task 2: Add Public Governance And Licensing

**Files:**
- Create: `AGENTS.md`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `SUPPORT.md`
- Create: `CHANGELOG.md`
- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `LICENSE`
- Modify: package manifests

**Interfaces:**
- Consumes: repository architecture, test commands, and dependency licenses.
- Produces: contributor and AI-agent operating contract plus accurate licensing boundaries.

- [x] Document architecture invariants, privacy constraints, testing requirements, and AI-assisted contribution disclosure in `AGENTS.md`.
- [x] Add contribution, security, conduct, support, and changelog policies.
- [x] Add third-party notices for yt-dlp, React, Tauri/Rust dependencies, and FFmpeg; document GPL-enabled binary-release obligations.
- [x] Declare MIT consistently in project package metadata without renaming compatibility-sensitive package identifiers.
- [x] Validate all policy links and remove placeholders.

### Task 3: Harden Public Configuration And Metadata

**Files:**
- Modify: `.gitignore`
- Create: `.editorconfig`
- Create: `.nvmrc`
- Modify: `README.md`
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/Info.plist`
- Modify: `src-tauri/src/main.rs`
- Modify: `engine/m3u8_bridge/server.py`
- Modify: docs and mockup metadata
- Test: `tests/test_branding.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: public identity and compatibility constraints.
- Produces: organization-neutral source defaults and `io.github.shumybest.yet-another-downloader` bundle identity.

- [x] Write failing tests for the new bundle identifier and empty proxy default.
- [x] Replace the bundle identifier in Tauri and deep-link setup while retaining the scheme.
- [x] Change the runtime proxy default to empty and keep localhost proxy only as an example placeholder.
- [x] Remove personal absolute paths from tracked metadata and improve ignore coverage.
- [x] Rewrite README for public users, contributors, privacy, legal use, architecture, and known limitations.
- [x] Run focused tests and verify compatibility identifiers remain unchanged.

### Task 4: Make Development And CI Reproducible

**Files:**
- Modify: `pyproject.toml`
- Modify: `scripts/bootstrap.sh`
- Modify: `package.json`
- Create: `scripts/check-public-tree.sh`
- Create: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Create: `.github/pull_request_template.md`

**Interfaces:**
- Consumes: frozen Node/Rust locks and pinned yt-dlp submodule.
- Produces: `pnpm verify` and least-privilege GitHub checks that need no repository secrets.

- [x] Add a public-tree test that rejects sensitive filenames, credential patterns, private absolute paths, and tracked build output.
- [x] Run the scanner against a fixture violation to prove it fails, then against the clean tree.
- [x] Declare Python tooling/development dependencies and align bootstrap installation.
- [x] Add typecheck, Python, Rust, public-tree, and aggregate verification commands.
- [x] Add GitHub Actions, Dependabot, issue forms, and PR checklist.
- [x] Validate YAML, shell syntax, package metadata, and local `pnpm verify` behavior.

### Task 5: Audit, Test, And Create The Initial Public Commit

**Files:**
- Verify: entire repository
- Create: first public Git commit

**Interfaces:**
- Consumes: completed public repository.
- Produces: one audited `main` commit ready for user-controlled GitHub push.

- [x] Run Node, Python, Rust, TypeScript, production build, formatting, and public-tree checks.
- [x] Scan tracked files and all newly created history for credentials, personal paths, generated binaries, and oversized objects.
- [x] Verify the yt-dlp commit, package identity, deep-link scheme, data-directory compatibility, and remote URL.
- [x] Set repository-local public author identity without exposing the previous email.
- [x] Create the first `chore: prepare initial open source release` commit and verify it has no parent.
- [x] Report any residual legal, signing, architecture, or GitHub settings work that cannot be completed locally.
