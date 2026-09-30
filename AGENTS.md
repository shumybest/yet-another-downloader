# AGENTS.md

This file defines the operating contract for AI coding agents and human contributors working in this repository. It applies to the entire tree unless a more specific `AGENTS.md` exists below a directory.

## Product

`yet another downloader` is a local-first macOS media downloader composed of:

- `apps/desktop`: React UI hosted by Tauri.
- `apps/chrome-extension`: Manifest V3 capture extension.
- `packages/capture-core`: media-resource classification.
- `packages/protocol`: loopback API types and client.
- `packages/ui`: shared UI and task/error presentation.
- `engine/m3u8_bridge`: Python download engine, HLS gateway, history, normalization, and validation.
- `src-tauri`: native lifecycle, sidecar, deep-link, resources, and packaging.
- `vendor/yt-dlp`: pinned upstream git submodule; do not edit it in this repository.

## Compatibility invariants

Do not change these without an explicit migration plan and tests:

- loopback port `8765`;
- deep-link scheme `m3u8bridge://`;
- `M3U8_BRIDGE_*` environment variables;
- internal package/module names containing `m3u8-bridge`;
- sidecar executable name `m3u8-bridge-engine`;
- existing data path `~/Library/Application Support/m3u8-bridge`.

The public bundle identifier is `io.github.shumybest.yet-another-downloader`.

## Security and privacy

- Never commit cookies, authorization headers, signed media URLs, tokens, private videos, user history databases, logs, credentials, or local configuration.
- Test URLs must use reserved domains such as `example.test` or loopback addresses.
- The deep link carries launch intent only. Do not place media URLs, headers, or tokens in it.
- The engine must bind to loopback. Mutating endpoints must retain session-token validation.
- Never terminate an unknown process occupying port `8765`.
- Do not weaken output validation merely to mark a task complete.
- Run `pnpm check:public` before proposing a commit.

## Editing rules

- Preserve unrelated user changes. Never use destructive Git commands to discard work.
- Prefer focused modules and tests over expanding already-large files.
- Add regression tests before fixing behavior.
- Keep generated files out of Git: `dist`, `build`, `target`, sidecars, bundled FFmpeg, staged extension resources, application bundles, databases, and logs.
- Update user documentation when behavior, settings, compatibility, packaging, or security assumptions change.
- Do not copy code from Cat-Catch. It is a GPL-3.0 behavioral reference only.
- Changes to the yt-dlp pin require release notes and relevant download regression tests.

## Required verification

Run the focused test while developing, then before completion run:

```sh
pnpm verify
```

For release packaging also run:

```sh
scripts/build-sidecar.sh
cargo tauri build --bundles app
```

Verify the app's signature, architecture, embedded extension, FFmpeg/ffprobe executability, cold start, loopback health, and sidecar cleanup. Binary distribution also requires the third-party license and corresponding-source checks in `THIRD_PARTY_NOTICES.md`.

## AI-assisted contributions

- Disclose material AI assistance in the pull request description.
- The contributor must inspect every changed line and generated asset.
- AI output does not establish correctness, authorship, provenance, or license compatibility.
- Never include prompts or logs containing credentials, private URLs, personal data, or proprietary source material.
- Do not claim tests passed unless the commands were run and their exit status was checked.
