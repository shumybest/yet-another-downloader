#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONDA_ENV="${M3U8_BRIDGE_CONDA_ENV:-m3u8-bridge}"
CONDA_BIN="${M3U8_BRIDGE_CONDA_BIN:-$(command -v conda 2>/dev/null || true)}"
if [ -z "$CONDA_BIN" ]; then
  for candidate in \
    /usr/local/bin/conda \
    /opt/homebrew/bin/conda \
    "$HOME/miniforge3/bin/conda" \
    "$HOME/mambaforge/bin/conda" \
    /usr/local/Caskroom/miniforge/base/bin/conda; do
    if [ -x "$candidate" ]; then CONDA_BIN="$candidate"; break; fi
  done
fi
TARGET="${TARGET_TRIPLE:-}"

run_python() {
  if [ -n "${M3U8_BRIDGE_PYTHON:-}" ]; then
    "$M3U8_BRIDGE_PYTHON" "$@"
  elif [ -n "$CONDA_BIN" ] && [ -x "$CONDA_BIN" ]; then
    "$CONDA_BIN" run --no-capture-output -n "$CONDA_ENV" python "$@"
  else
    echo "Miniforge conda is required. Set M3U8_BRIDGE_CONDA_BIN or M3U8_BRIDGE_PYTHON." >&2
    return 1
  fi
}

if ! run_python -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller is missing. Run scripts/bootstrap.sh or install it in conda environment '$CONDA_ENV'." >&2
  exit 1
fi
if [ -z "$TARGET" ]; then
  case "$(uname -m)" in
    arm64) TARGET="aarch64-apple-darwin" ;;
    x86_64) TARGET="x86_64-apple-darwin" ;;
    *) echo "Unsupported macOS architecture: $(uname -m)" >&2; exit 1 ;;
  esac
fi

cd "$ROOT"
run_python -m PyInstaller --clean --noconfirm --onefile --name m3u8-bridge-engine \
  --paths "$ROOT/engine" --paths "$ROOT/vendor/yt-dlp" --collect-submodules yt_dlp \
  "$ROOT/engine/sidecar_entry.py"

mkdir -p "$ROOT/src-tauri/binaries"
for artifact in "$ROOT/src-tauri/binaries/ffmpeg" "$ROOT/src-tauri/binaries/ffprobe" "$ROOT/src-tauri/binaries/m3u8-bridge-engine-$TARGET"; do
  [ -e "$artifact" ] && chmod u+w "$artifact"
done
cp "$ROOT/dist/m3u8-bridge-engine" "$ROOT/src-tauri/binaries/m3u8-bridge-engine-$TARGET"
cp "${M3U8_BRIDGE_FFMPEG:-$(command -v ffmpeg)}" "$ROOT/src-tauri/binaries/ffmpeg"
cp "${M3U8_BRIDGE_FFPROBE:-$(command -v ffprobe)}" "$ROOT/src-tauri/binaries/ffprobe"
chmod +x "$ROOT/src-tauri/binaries/m3u8-bridge-engine-$TARGET" "$ROOT/src-tauri/binaries/ffmpeg" "$ROOT/src-tauri/binaries/ffprobe"
if [ "$(uname -s)" = "Darwin" ]; then
  run_python "$ROOT/scripts/bundle_macos_dylibs.py" \
    --binary "$ROOT/src-tauri/binaries/ffmpeg" \
    --binary "$ROOT/src-tauri/binaries/ffprobe" \
    --lib-dir "$ROOT/src-tauri/binaries/lib"
fi

# Tauri 1.x preserves source permissions when staging resources. Homebrew dylibs
# can therefore leave read-only copies that a later build cannot overwrite.
for profile in debug release; do
  staged_binaries="$ROOT/src-tauri/target/$profile/binaries"
  if [ -d "$staged_binaries" ]; then
    chmod -R u+w "$staged_binaries"
    rm -rf "$staged_binaries"
  fi
done

echo "Sidecars prepared for $TARGET. Run pnpm tauri:build next."
