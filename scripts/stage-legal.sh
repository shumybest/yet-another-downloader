#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESTINATION="$ROOT/src-tauri/resources/legal"
STAGING="$ROOT/src-tauri/resources/.legal-staging"

for source in \
  "$ROOT/LICENSE" \
  "$ROOT/THIRD_PARTY_NOTICES.md" \
  "$ROOT/licenses/YT-DLP-UNLICENSE.txt" \
  "$ROOT/licenses/FFMPEG-GPL-3.0.txt"; do
  if [ ! -f "$source" ]; then
    echo "Required legal file is missing: $source" >&2
    exit 1
  fi
done

mkdir -p "$ROOT/src-tauri/resources"
if [ -e "$STAGING" ]; then
  find "$STAGING" -depth -delete
fi
mkdir -p "$STAGING"
cp "$ROOT/LICENSE" "$STAGING/PROJECT-GPL-3.0-or-later.txt"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$STAGING/THIRD_PARTY_NOTICES.md"
cp "$ROOT/licenses/YT-DLP-UNLICENSE.txt" "$STAGING/YT-DLP-UNLICENSE.txt"
cp "$ROOT/licenses/FFMPEG-GPL-3.0.txt" "$STAGING/FFMPEG-GPL-3.0.txt"
if [ -n "${M3U8_BRIDGE_RELEASE_LEGAL_DIR:-}" ]; then
  if [ ! -d "$M3U8_BRIDGE_RELEASE_LEGAL_DIR" ]; then
    echo "Generated release legal directory is missing: $M3U8_BRIDGE_RELEASE_LEGAL_DIR" >&2
    exit 1
  fi
  cp -R "$M3U8_BRIDGE_RELEASE_LEGAL_DIR"/. "$STAGING"/
fi
if [ -e "$DESTINATION" ]; then
  find "$DESTINATION" -depth -delete
fi
mv "$STAGING" "$DESTINATION"
echo "Legal notices staged at $DESTINATION"
