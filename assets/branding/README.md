# Branding assets

`icon-source.png` is the source artwork for the application and Chrome extension icons. It was generated with Tencent VOD image-generation tooling under the project maintainer's direction, then reviewed and post-processed to create a true transparent background.

Derived platform sizes under `src-tauri/icons`, `apps/desktop/public`, and `apps/chrome-extension/public/icons` are project assets distributed under GPL-3.0-or-later.

Regenerate Tauri icon sizes with:

```sh
cargo tauri icon assets/branding/icon-source.png
```

Review the source and 16 px output visually before replacing published icons.
