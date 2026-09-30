# Open-source publication audit

Audit date: 2026-09-30

## Cleared for source publication

- No cloud credentials, private keys, cookies, bearer tokens, signed production media URLs, or credential files were found in the reviewed source tree.
- The repository was rebuilt with a new public history; the previous draft commit and its author email are not ancestors of `main`.
- Personal absolute paths were removed from tracked mockup and planning metadata.
- The organization-specific macOS identity was replaced by `io.github.shumybest.yet-another-downloader`.
- New installations no longer assume a local proxy; loopback proxy addresses remain only in examples and synthetic tests.
- Build outputs, sidecars, staged resources, local databases, logs, environments, application bundles, archives, signing material, and editor state are ignored.
- The yt-dlp dependency is a pinned public submodule and its Unlicense text is included.

## Residual release gates

- The project was relicensed to GPL-3.0-or-later for binary publication. The tested FFmpeg build enables GPL components and every release still requires the complete binary-distribution compliance process described in `THIRD_PARTY_NOTICES.md`.
- Apple Developer ID signing and notarization are not configured.
- Only Intel `x86_64` packaging has been verified; Apple Silicon needs a separate native build and test.
- GitHub repository settings such as private vulnerability reporting, Discussions, branch protection, required checks, secret scanning, and Dependabot alerts must be enabled after the repository exists on GitHub.

## Automated guard

Run `pnpm check:public` before every public commit. The check examines Git candidates, including untracked files not excluded by `.gitignore`, for sensitive filenames, credential patterns, personal paths, generated artifacts, and oversized source files.
