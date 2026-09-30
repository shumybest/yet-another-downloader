#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/src-tauri/Cargo.toml"

# Source checks must not require ignored sidecar and bundled-resource artifacts.
export TAURI_CONFIG='{"tauri":{"bundle":{"externalBin":[],"resources":[]}}}'

cargo fmt --check --manifest-path "$MANIFEST"
cargo test --locked --manifest-path "$MANIFEST"
cargo check --locked --manifest-path "$MANIFEST"
