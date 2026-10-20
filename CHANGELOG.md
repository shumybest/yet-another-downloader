# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.3] - 2026-10-20

### Added

- Desktop startup stages for local-service checks, Python preparation, process launch, history recovery, yt-dlp loading, and API readiness, with elapsed time and retry counts.
- Packaged-engine stdout/stderr logging and actionable port-conflict diagnostics including the listener process and PID.

### Fixed

- Slow or incomplete health checks no longer falsely classify a listener as an incompatible engine; complete Content-Length responses do not wait for socket closure.
- Engine startup and restart run in the background, preserve failure details, and support retry after resolving port conflicts.
- Restart waits for the managed engine's port to release before reconnecting; the desktop refreshes its API session after restart and avoids overlapping polling.
- Startup detects early process exit and does not leave an owned engine running after the desktop quits.

## [0.1.2] - 2026-10-08

### Added

- Desktop form for manually creating HLS, DASH, and direct-video download tasks from media URLs, including extensionless links with an explicit media type.

### Changed

- Synchronized desktop, engine, Chrome extension, and package versions to 0.1.2.

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

[Unreleased]: https://github.com/shumybest/yet-another-downloader/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/shumybest/yet-another-downloader/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/shumybest/yet-another-downloader/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/shumybest/yet-another-downloader/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/shumybest/yet-another-downloader/releases/tag/v0.1.0
