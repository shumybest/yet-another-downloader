# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-10-01

### Added

- Public contribution, security, support, AI-agent, and repository governance documentation.
- CI, dependency update configuration, issue forms, pull-request template, and public-tree scanning.
- macOS menu bar controls for restoring the desktop window, viewing aggregate live download speed, and explicitly quitting the app.

### Changed

- Public product identity is now `yet another downloader` with the bundle identifier `io.github.shumybest.yet-another-downloader`.
- New installations start with proxying disabled; existing saved proxy settings remain compatible.
- Closing the main window now keeps active downloads running in the background.

### Fixed

- CI now declares the Node.js type dependency used by tests and runs the Rust job on an available macOS runner.

## [0.1.0] - 2026-09-30

### Added

- Tauri desktop download manager with persistent local history and engine lifecycle controls.
- Chrome extension for HLS, DASH, and direct-media discovery with rendition metadata.
- yt-dlp and FFmpeg download, normalization, validation, proxy, cancellation, retry, and stall protection.
- Packaged extension installation and browser-to-desktop activation.

[Unreleased]: https://github.com/shumybest/yet-another-downloader/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/shumybest/yet-another-downloader/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/shumybest/yet-another-downloader/releases/tag/v0.1.0
