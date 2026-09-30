# Contributing

Thank you for improving `yet another downloader`.

## Before opening an issue

- Search existing issues.
- Remove cookies, tokens, signed URLs, private media, usernames, and local paths from logs.
- Confirm you are authorized to access and download the media involved.
- Use GitHub's private vulnerability reporting for security issues; see [SECURITY.md](SECURITY.md).

## Development

1. Fork and clone with submodules: `git clone --recurse-submodules <your-fork-url>`.
2. Install the prerequisites in [README.md](README.md).
3. Run `corepack enable`, `pnpm install --frozen-lockfile`, and `scripts/bootstrap.sh`.
4. Create a focused branch from `main`.
5. Add or update tests before changing behavior.
6. Run `pnpm verify` before opening a pull request.

Internal names such as `m3u8-bridge-engine`, `M3U8_BRIDGE_*`, `m3u8bridge://`, and the existing Application Support directory are compatibility interfaces. Do not rename them as cosmetic cleanup.

## Pull requests

- Keep each pull request focused and explain the user-visible effect.
- Include reproduction steps for fixes and screenshots for UI changes.
- State exactly which verification commands ran.
- Disclose material use of AI coding or image-generation tools.
- Do not commit generated builds, downloaded media, local databases, logs, or secrets.
- Update `CHANGELOG.md` for user-visible behavior.

## Commit certification

Contributions use the [Developer Certificate of Origin 1.1](https://developercertificate.org/). Sign off each commit:

```sh
git commit -s -m "fix: describe the change"
```

The sign-off certifies that you have the right to submit the contribution under this project's license. AI assistance does not replace this responsibility.

## License

By contributing original project code, you agree that it is licensed under MIT. Do not submit third-party code unless its provenance and license are documented and compatible. The pinned yt-dlp submodule and FFmpeg binaries retain their upstream licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
