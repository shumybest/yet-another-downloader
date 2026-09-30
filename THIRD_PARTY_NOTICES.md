# Third-Party Notices

`yet another downloader` contains or interfaces with third-party software. The repository's [MIT License](LICENSE) applies only to original project code and assets unless a file says otherwise.

## Source dependencies

### yt-dlp

- Upstream: <https://github.com/yt-dlp/yt-dlp>
- Integration: pinned git submodule at `vendor/yt-dlp`
- License: The Unlicense
- License text: [licenses/YT-DLP-UNLICENSE.txt](licenses/YT-DLP-UNLICENSE.txt)

### React and JavaScript dependencies

React, React DOM, and direct runtime JavaScript dependencies are distributed under their upstream licenses, primarily MIT. Exact versions are recorded in `pnpm-lock.yaml`. Run `pnpm licenses list --prod` to inspect the resolved production tree.

### Tauri and Rust dependencies

The Tauri shell and Rust crates retain their upstream licenses. Exact versions are recorded in `src-tauri/Cargo.lock`. Consult each package's registry metadata before redistribution.

### Cat-Catch

Cat-Catch was studied as a behavioral reference. No Cat-Catch source code is copied or included in this repository or its build. Cat-Catch itself is GPL-3.0 licensed.

## FFmpeg and packaged releases

FFmpeg is a system prerequisite for source development and may be copied into locally built application bundles by `scripts/build-sidecar.sh`. FFmpeg is not licensed under this project's MIT License.

The Homebrew FFmpeg build used during current macOS testing reports GPLv3-or-later and enables GPL components including x264 and x265. A distributor of an application containing that build is responsible for all applicable obligations, including:

- shipping the applicable license and copyright notices;
- publishing the exact FFmpeg build configuration;
- providing complete corresponding source, including relevant build scripts and enabled linked libraries, or another legally sufficient source mechanism;
- satisfying the licenses of every bundled dynamic library;
- avoiding claims that the entire binary bundle is MIT licensed.

The GPLv3 text used by verified local builds is included at [licenses/FFMPEG-GPL-3.0.txt](licenses/FFMPEG-GPL-3.0.txt). This file alone does not complete the corresponding-source obligation.

Automated public binary releases are intentionally disabled until signing, notarization, architecture coverage, complete license inventory, and corresponding-source delivery are reproducible and reviewed. Source-only publication of this repository does not include the generated FFmpeg binaries because `src-tauri/binaries` is ignored.

This notice is an engineering compliance aid, not legal advice.
