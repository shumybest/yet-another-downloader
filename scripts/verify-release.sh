#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 APP_PATH COMPLIANCE_DIR ARCHITECTURE" >&2
  exit 2
fi

APP="$1"
COMPLIANCE="$2"
ARCHITECTURE="$3"
RESOURCES="$APP/Contents/Resources"

[ -d "$APP" ] || { echo "Application bundle not found: $APP" >&2; exit 1; }
codesign --verify --deep --strict --verbose=2 "$APP"

for required in \
  "$RESOURCES/binaries/ffmpeg" \
  "$RESOURCES/binaries/ffprobe" \
  "$RESOURCES/resources/chrome-extension/manifest.json" \
  "$RESOURCES/resources/legal/PROJECT-GPL-3.0-or-later.txt" \
  "$RESOURCES/resources/legal/THIRD_PARTY_NOTICES.md" \
  "$RESOURCES/resources/legal/RELEASE-MANIFEST.json" \
  "$RESOURCES/resources/legal/MACHO-DEPENDENCIES.json" \
  "$RESOURCES/resources/legal/SOURCE-OFFER.txt" \
  "$COMPLIANCE/HOMEBREW-COMPONENTS.json"; do
  [ -e "$required" ] || { echo "Required release file missing: $required" >&2; exit 1; }
done

for executable in "$APP/Contents/MacOS"/* "$RESOURCES/binaries/ffmpeg" "$RESOURCES/binaries/ffprobe"; do
  file "$executable" | grep -q "$ARCHITECTURE" || {
    echo "Unexpected architecture for $executable" >&2
    exit 1
  }
done

while IFS= read -r -d '' candidate; do
  if file "$candidate" | grep -q 'Mach-O'; then
    if otool -L "$candidate" | grep -Eq '/usr/local/|/opt/homebrew/'; then
      echo "Non-portable Homebrew dependency remains in $candidate" >&2
      otool -L "$candidate" >&2
      exit 1
    fi
  fi
done < <(find "$APP" -type f -print0)

"$RESOURCES/binaries/ffmpeg" -version >/dev/null
"$RESOURCES/binaries/ffprobe" -version >/dev/null
echo "Static release verification passed for $APP"
