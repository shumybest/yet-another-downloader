# GPL Binary Release Design

## Goal

Publish the existing Intel macOS application as a reproducible GitHub pre-release without changing its runtime architecture, while meeting the redistribution obligations created by the bundled GPL-enabled Homebrew FFmpeg build.

## Licensing

Original project code is relicensed from MIT to GPL-3.0-or-later. Third-party components retain their own licenses. The release must not describe the entire bundle as being under a single license.

The application remains a Tauri desktop shell that starts the PyInstaller Python/yt-dlp sidecar and invokes bundled FFmpeg/ffprobe executables. No runtime protocol, data path, port, deep-link scheme, or download behavior changes.

## Release Artifacts

The `v0.1.0` Intel pre-release contains:

- an ad-hoc-signed macOS application ZIP;
- an Intel macOS DMG containing the same signed application;
- a corresponding-source archive containing the tagged project source, initialized yt-dlp submodule, exact Homebrew formulae and receipts, dependency license files, and fetched source inputs for the bundled FFmpeg dependency graph;
- SHA-256 checksums and machine-readable dependency manifests.

The application embeds the project license, third-party notice, FFmpeg build configuration, bundled-library manifest, and a source offer pointing to the matching GitHub release.

## Verification

Release verification covers the normal `pnpm verify` suite, source-tree cleanliness, Mach-O architecture and dependency closure, embedded legal files and Chrome extension, ad-hoc signature verification, cold-start engine health, activation, parent-process cleanup, archive extraction, checksums, and agreement between the tag, application version, and release filenames.

## Distribution Limits

The first release is Intel-only and is not notarized because no Apple Developer ID identity is available. GitHub release notes must identify it as a pre-release and explain the expected Gatekeeper warning. This is an engineering compliance process and not legal advice.
