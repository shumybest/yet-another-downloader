#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/apps/chrome-extension/dist"
DESTINATION="$ROOT/src-tauri/resources/chrome-extension"

if [ ! -f "$SOURCE/manifest.json" ]; then
  echo "Chrome extension build is missing: $SOURCE/manifest.json" >&2
  exit 1
fi

STAGING="$ROOT/src-tauri/resources/.chrome-extension-staging"
mkdir -p "$ROOT/src-tauri/resources"
if [ -e "$STAGING" ]; then
  find "$STAGING" -depth -delete
fi
mkdir -p "$STAGING"
cp -R "$SOURCE/." "$STAGING/"
if [ -e "$DESTINATION" ]; then
  find "$DESTINATION" -depth -delete
fi
mv "$STAGING" "$DESTINATION"
echo "Chrome extension staged at $DESTINATION"
