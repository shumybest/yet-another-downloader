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

if [ -n "${M3U8_BRIDGE_PYTHON:-}" ]; then
  PYTHON_CMD=("$M3U8_BRIDGE_PYTHON")
elif [ -n "$CONDA_BIN" ] && [ -x "$CONDA_BIN" ]; then
  CONDA_BASE="$("$CONDA_BIN" info --base)"
  ENV_PYTHON="$CONDA_BASE/envs/$CONDA_ENV/bin/python"
  if [ "$CONDA_ENV" = "base" ]; then ENV_PYTHON="$CONDA_BASE/bin/python"; fi
  if [ -x "$ENV_PYTHON" ]; then
    PYTHON_CMD=("$ENV_PYTHON")
  else
    PYTHON_CMD=("$CONDA_BIN" run --no-capture-output -n "$CONDA_ENV" python)
  fi
else
  echo "Miniforge conda is required. Set M3U8_BRIDGE_CONDA_BIN or M3U8_BRIDGE_PYTHON." >&2
  exit 1
fi

cd "$ROOT"
PYTHONPATH="$ROOT/engine:$ROOT/vendor/yt-dlp${PYTHONPATH:+:$PYTHONPATH}" exec "${PYTHON_CMD[@]}" -m m3u8_bridge.server
