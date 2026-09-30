#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_VERSION="3.13"
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
if [ -z "$CONDA_BIN" ] || [ ! -x "$CONDA_BIN" ]; then
  echo "Miniforge conda is required. Set M3U8_BRIDGE_CONDA_BIN to the conda executable." >&2
  exit 1
fi

command -v ffmpeg >/dev/null || { echo "ffmpeg is required for development. Install it with: brew install ffmpeg" >&2; exit 1; }

if ! "$CONDA_BIN" env list | awk '{print $1}' | grep -Fxq "$CONDA_ENV"; then
  "$CONDA_BIN" create -y -n "$CONDA_ENV" "python=$PYTHON_VERSION" pip
fi

if [ -f "$ROOT/vendor/yt-dlp/pyproject.toml" ]; then
  "$CONDA_BIN" run --no-capture-output -n "$CONDA_ENV" python -m pip install -r "$ROOT/requirements-build.txt" -e "$ROOT/vendor/yt-dlp[default]"
else
  echo "yt-dlp submodule is missing. Run: git submodule update --init --recursive" >&2
  exit 1
fi
echo "Development runtime ready: conda environment '$CONDA_ENV'. Start the app with: pnpm tauri:dev"
