#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = "--" ]; then
  shift
fi
VERSION="${1:-v0.1.0}"
ARCHITECTURE="$(uname -m)"
CONDA_ENV="${M3U8_BRIDGE_RELEASE_CONDA_ENV:-m3u8-bridge-release}"
CONDA_BIN="${M3U8_BRIDGE_CONDA_BIN:-/usr/local/bin/conda}"
export PYTHONNOUSERSITE=1
OUTPUT="$ROOT/release/$VERSION"
COMPLIANCE="$OUTPUT/compliance"
APP_LEGAL="$OUTPUT/app-legal"
APP="$ROOT/src-tauri/target/release/bundle/macos/yet another downloader.app"
APP_ZIP="$OUTPUT/yet-another-downloader-$VERSION-macos-$ARCHITECTURE.zip"
DMG="$OUTPUT/yet-another-downloader-$VERSION-macos-$ARCHITECTURE.dmg"
SOURCE_ARCHIVE="$OUTPUT/yet-another-downloader-$VERSION-corresponding-source.tar.gz"
DMG_STAGING=""
SOURCE_STAGING=""

cleanup() {
  [ -z "$DMG_STAGING" ] || rm -rf "$DMG_STAGING"
  [ -z "$SOURCE_STAGING" ] || rm -rf "$SOURCE_STAGING"
}
trap cleanup EXIT

if ! [[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]]; then
  echo "Version must look like v0.1.0" >&2
  exit 2
fi
if [ "$ARCHITECTURE" != "x86_64" ]; then
  echo "This release procedure is currently validated only for x86_64." >&2
  exit 1
fi
if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]; then
  echo "Release packaging requires a clean Git working tree." >&2
  exit 1
fi
if [ ! -x "$CONDA_BIN" ]; then
  echo "Miniforge conda was not found at $CONDA_BIN" >&2
  exit 1
fi

mkdir -p "$OUTPUT"
if ! "$CONDA_BIN" env list | awk '{print $1}' | grep -Fxq "$CONDA_ENV"; then
  "$CONDA_BIN" create -y -n "$CONDA_ENV" python=3.13 pip
fi
PYTHON="$($CONDA_BIN run -n "$CONDA_ENV" python -c 'import sys; print(sys.executable)')"
"$CONDA_BIN" run --no-capture-output -n "$CONDA_ENV" \
  python -m pip install --disable-pip-version-check -r "$ROOT/requirements-build.txt" \
  -e "$ROOT/vendor/yt-dlp[default]"

pnpm verify
python3 "$ROOT/scripts/release_compliance.py" \
  --project-root "$ROOT" \
  --output "$COMPLIANCE" \
  --ffmpeg "${M3U8_BRIDGE_FFMPEG:-$(command -v ffmpeg)}" \
  --ffprobe "${M3U8_BRIDGE_FFPROBE:-$(command -v ffprobe)}" \
  --python "$PYTHON" \
  --version "$VERSION" \
  --architecture "$ARCHITECTURE" \
  --fetch-sources

mkdir -p "$APP_LEGAL"
rsync -a \
  --exclude='sources/' \
  --exclude='homebrew-sources/' \
  --exclude='python-sources/' \
  --exclude='fetch.log' \
  "$COMPLIANCE"/ "$APP_LEGAL"/

M3U8_BRIDGE_PYTHON="$PYTHON" scripts/build-sidecar.sh
M3U8_BRIDGE_RELEASE_LEGAL_DIR="$APP_LEGAL" cargo tauri build --bundles app
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
scripts/verify-release.sh "$APP" "$COMPLIANCE" "$ARCHITECTURE"

ditto -c -k --sequesterRsrc --keepParent "$APP" "$APP_ZIP"
DMG_STAGING="$(mktemp -d "$OUTPUT/.dmg-staging.XXXXXX")"
cp -R "$APP" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"
hdiutil create -volname "yet another downloader" -srcfolder "$DMG_STAGING" -ov -format UDZO "$DMG"

SOURCE_STAGING="$(mktemp -d "$OUTPUT/.source-staging.XXXXXX")"
SOURCE_ROOT="$SOURCE_STAGING/yet-another-downloader-$VERSION"
mkdir -p "$SOURCE_ROOT"
git -C "$ROOT" archive HEAD | tar -xf - -C "$SOURCE_ROOT"
mkdir -p "$SOURCE_ROOT/vendor/yt-dlp"
git -C "$ROOT/vendor/yt-dlp" archive HEAD | tar -xf - -C "$SOURCE_ROOT/vendor/yt-dlp"
cp -R "$COMPLIANCE" "$SOURCE_ROOT/release-compliance"
tar -czf "$SOURCE_ARCHIVE" -C "$SOURCE_STAGING" "yet-another-downloader-$VERSION"

(
  cd "$OUTPUT"
  shasum -a 256 \
    "$(basename "$APP_ZIP")" \
    "$(basename "$DMG")" \
    "$(basename "$SOURCE_ARCHIVE")" > SHA256SUMS.txt
  shasum -a 256 -c SHA256SUMS.txt
)

echo "Release assets are ready in $OUTPUT"
