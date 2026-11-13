#!/usr/bin/env bash
# Builds the bridge as a single file for macOS or Linux (no Python needed to run it):
#   dist/PixelsFGU-Bridge-macos-arm64  or  dist/PixelsFGU-Bridge-linux-x86_64
# The release workflow (.github/workflows/release.yml) runs the same PyInstaller command.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root/bridge"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements-dev.txt

arch="$(uname -m)"; [ "$arch" = aarch64 ] && arch=arm64; [ "$arch" = amd64 ] && arch=x86_64
case "$(uname -s)" in
  Darwin) name="PixelsFGU-Bridge-macos-$arch"; collect="--collect-submodules CoreBluetooth --collect-submodules libdispatch" ;;
  Linux)  name="PixelsFGU-Bridge-linux-$arch"; collect="--collect-submodules dbus_fast" ;;
  *) echo "Use tools/build-bridge.ps1 on Windows" >&2; exit 1 ;;
esac

# shellcheck disable=SC2086
.venv/bin/python -m PyInstaller --noconfirm --clean --onefile --name "$name" \
  --collect-submodules bleak $collect \
  --distpath "$root/dist" --workpath "$root/build" --specpath "$root/build" \
  pixels_bridge.py
echo "Built dist/$name"
