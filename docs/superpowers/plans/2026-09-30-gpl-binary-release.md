# GPL Binary Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Produce and publish a verified Intel macOS `v0.1.0` pre-release with complete license and corresponding-source materials.

**Architecture:** Keep the current Tauri, Python sidecar, yt-dlp, FFmpeg, extension, and loopback interfaces unchanged. Add release-only tooling that inventories the actual binaries, stages legal files, assembles corresponding source, signs packages, and verifies release assets.

**Tech Stack:** Bash, Python 3.13, Homebrew, PyInstaller, Tauri 1/Rust, pnpm, GitHub Releases.

**Spec:** `docs/superpowers/specs/2026-09-30-gpl-binary-release-design.md`

## Global Constraints

- Do not change port `8765`, `m3u8bridge://`, `M3U8_BRIDGE_*`, the sidecar name, or the existing application data directory.
- Do not commit generated binaries, release archives, source archives, caches, credentials, or local absolute paths.
- Do not publish unless all release checks pass.
- Mark the release as Intel-only, ad-hoc signed, not notarized, and pre-release.

---

### Task 1: Relicense Original Project Code

**Files:** `LICENSE`, package manifests, `README.md`, `THIRD_PARTY_NOTICES.md`, contributor documentation, licensing tests.

- [ ] Add a failing test requiring GPL-3.0-or-later across project manifests and staged legal resources.
- [ ] Replace the root MIT license with GPLv3 and update SPDX metadata and documentation.
- [ ] Preserve all third-party license boundaries and describe binary redistribution requirements.
- [ ] Run focused license tests and the public-tree scanner.

### Task 2: Generate Reproducible Compliance Materials

**Files:** release compliance generator, legal staging script, release tests, deployment and testing documentation.

- [ ] Add tests for Mach-O dependency-to-Homebrew mapping, manifest generation, and required release files.
- [ ] Inventory actual bundled binaries and recursively resolved non-system libraries.
- [ ] Collect exact installed Homebrew formulae, receipts, license files, FFmpeg configuration, and source inputs.
- [ ] Collect Node, Rust, Python, PyInstaller, Python runtime, and yt-dlp license metadata.
- [ ] Build a corresponding-source archive that includes the project source and yt-dlp submodule.

### Task 3: Build And Verify Release Assets

**Files:** release packaging and verification scripts; generated ignored release directory.

- [ ] Create a clean dedicated Conda build environment and build the sidecar.
- [ ] Build the macOS application, stage legal resources, apply ad-hoc signing, and create ZIP and DMG assets.
- [ ] Verify architecture, dependency closure, signatures, embedded resources, cold start, health, activation, and sidecar cleanup.
- [ ] Generate and verify SHA-256 checksums for every uploaded asset.

### Task 4: Publish GitHub Pre-release

**Files:** release notes and Git metadata.

- [ ] Run `pnpm verify` and all release-specific verification on the final tree.
- [ ] Commit and push source changes, create and push annotated tag `v0.1.0`.
- [ ] Create the GitHub pre-release and upload the verified binary, source, manifest, and checksum assets.
- [ ] Verify the published release page and downloadable asset checksums.
