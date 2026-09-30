#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${M3U8_BRIDGE_PYTHON:-python3}"

exec "$PYTHON" "$ROOT/scripts/check_public_tree.py"
