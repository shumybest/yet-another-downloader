# Open Source Readiness Design (Superseded)

> Status: superseded historical record. Do not use its MIT-only release decisions for current builds. The project was subsequently relicensed under GPL-3.0-or-later; see `2026-09-30-gpl-binary-release-design.md`.

## Goal

Publish `shumybest/yet-another-downloader` as a clean, reproducible, contributor-friendly open-source repository without leaking local credentials, personal filesystem paths, private development history, or misleading users about third-party license obligations.

## Canonical Repository

The public repository is the `yet-another-downloader` checkout and publishes to:

```text
https://github.com/shumybest/yet-another-downloader.git
```

Migration copies reviewed source-controlled content from the latest detached implementation into the canonical repository. Build output, virtual environments, caches, generated sidecars, staged extension output, and stale Git metadata are excluded. The canonical repository then receives a new public `main` history with no parent commit. The detached source directory is marked deprecated and is not automatically deleted.

## Public Identity And Compatibility

- Product name: `yet another downloader`.
- GitHub owner and repository: `shumybest/yet-another-downloader`.
- macOS bundle identifier: `io.github.shumybest.yet-another-downloader`.
- Git remote: `https://github.com/shumybest/yet-another-downloader.git`.
- The public Git history must not retain the old author email or private draft commit.
- Compatibility-sensitive runtime identifiers remain unchanged: `m3u8bridge://`, port `8765`, `M3U8_BRIDGE_*`, internal npm/Python/Rust package names, sidecar filename, and `~/Library/Application Support/m3u8-bridge`.
- User-visible documentation explains why internal compatibility names still contain `m3u8-bridge`.

## Repository Governance

Create focused public-maintenance documents:

- `AGENTS.md`: repository map, invariants, safe edit rules, required tests, privacy rules, and AI-assisted development disclosure expectations.
- `CONTRIBUTING.md`: environment setup, submodules, branch and commit guidance, test matrix, PR requirements, and legal attestation through Developer Certificate of Origin sign-off.
- `SECURITY.md`: supported version, private vulnerability reporting through GitHub Security Advisories, prohibited public disclosure of exploitable details, and local-engine threat boundaries.
- `CODE_OF_CONDUCT.md`: Contributor Covenant 2.1 with an owner-managed enforcement contact that does not publish a private email address.
- `SUPPORT.md`: supported questions, diagnostics that are safe to share, and a warning never to post cookies, tokens, signed media URLs, or private videos.
- `CHANGELOG.md`: Keep a Changelog structure beginning at `0.1.0`.
- `.github` templates: structured bug, feature and security-routing forms plus a pull-request checklist.
- `.github/dependabot.yml`: weekly npm, Cargo, GitHub Actions, and git-submodule updates.

## Licensing

The repository's original code remains MIT licensed. Package manifests declare that license consistently.

`THIRD_PARTY_NOTICES.md` distinguishes source dependencies from bundled release components:

- yt-dlp is pinned as a git submodule and distributed under the Unlicense.
- React and the direct JavaScript runtime dependencies are MIT licensed.
- Tauri and direct Rust dependencies use their upstream licenses.
- Cat-Catch is a behavioral reference only; no Cat-Catch source is included.
- FFmpeg is not covered by this repository's MIT license. The current Homebrew build enables GPL components, so any distributed application containing that binary must include the applicable GPL license, copyright notices, exact build configuration, and corresponding source or a legally sufficient source offer. Public binary release automation remains out of scope until that process is reproducible and verified.

The source repository must not claim that every bundled binary is MIT licensed. This is a compliance warning, not legal advice.

## Secrets And Privacy

The public tree must pass an automated `scripts/check-public-tree.sh` check covering:

- common credential filenames and private key extensions;
- known cloud access-key, bearer-token, cookie, signed-query, and embedded-basic-auth patterns;
- `/Users/...` personal absolute paths;
- production media URLs and captured headers;
- generated application binaries, build trees, environment files, databases, logs, and local configuration.

Examples use reserved domains and placeholder variables. The proxy setting defaults to empty; `http://127.0.0.1:7890` remains only as an explicitly labelled example, never as an assumed runtime default. Tests use synthetic reserved-domain URLs.

The initial audit found no actual secret, cookie, signed production URL, or credential file in the latest source tree. It did find personal absolute paths in mockup metadata, a private author email in the old commit, an organization-specific bundle identifier, and a hard-coded local proxy default. All four are removed from the public repository or isolated behind compatibility behavior before publication.

## Build And Dependency Reproducibility

- Pin Node and pnpm versions for contributors and CI.
- Keep `pnpm-lock.yaml`, `src-tauri/Cargo.lock`, and the yt-dlp submodule commit tracked.
- Declare Python development/build dependencies explicitly rather than relying on an already-populated conda environment.
- Keep generated extension bundles, sidecars, ffmpeg binaries, PyInstaller output, application bundles, and local databases untracked.
- Add a single `pnpm verify` command that runs public-tree checks, TypeScript checking, Node tests, Python tests/byte-compilation, Rust formatting/tests/checks, and production web builds.

## Continuous Integration

GitHub Actions uses least-privilege read-only permissions and pinned major action versions. CI runs:

1. Public-tree and credential-pattern checks.
2. Node install with frozen lockfile, typecheck, tests, and desktop/extension builds.
3. Python 3.13 unit tests and byte compilation with the yt-dlp submodule initialized.
4. Rust formatting, tests, and checks on macOS because the Tauri shell is macOS-specific.

CI does not publish binaries, sign applications, access secrets, or download protected media. Binary releases remain a documented manual process until signing, notarization, architecture coverage, and FFmpeg source-license compliance are all available.

## README And User Safety

The README leads with the product purpose, screenshot, supported media types, architecture, quick start, browser extension workflow, privacy model, legal-use warning, known limitations, and links to contributor/security documents. It states that users are responsible for authorization and applicable terms and law; the project must not be represented as bypassing DRM, paywalls, access control, rate limits, or copyright restrictions.

## Verification

Before creating the clean initial commit:

- run the public-tree scanner and inspect every finding;
- run all Node, Python, and Rust tests;
- run TypeScript checking and production web builds;
- run `git diff --check` before history replacement;
- initialize the fresh repository, verify the submodule commit, remote URL, tracked-file inventory, largest objects, author identity, and full-tree secret scan;
- confirm ignored build artifacts remain untracked;
- confirm the previous source directory is marked deprecated and the canonical directory is the only active Git checkout.

No push to GitHub occurs without a separate explicit user request.
