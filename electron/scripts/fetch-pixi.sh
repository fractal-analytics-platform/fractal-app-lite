#!/usr/bin/env bash
# Downloads the pixi executable for the current OS/CPU and places it next to
# the PyInstaller-built backend executable, so the packaged app does not depend
# on pixi being installed on the user's machine. At runtime,
# fractal_lite._execution.pixi_executable() looks for it there.
#
# Source: https://github.com/prefix-dev/pixi/releases
# Output: resources/fractal-app-lite/pixi  (pixi.exe on Windows)
#
# Must run after scripts/build-backend.sh, which recreates
# resources/fractal-app-lite/ from scratch (build-backend.sh calls this script
# at its end).
#
# Usage:
#   bash scripts/fetch-pixi.sh
#
# The bundled pixi version is pinned below, so every build ships the same
# pixi. Keep it in sync with the `pixi-version` used by the GitHub workflows.
# Set PIXI_VERSION to override it (PIXI_VERSION=latest for the latest release).
set -euo pipefail

ELECTRON_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="$ELECTRON_ROOT/resources/fractal-app-lite"

if [[ ! -d "$DEST_DIR" ]]; then
  echo "Error: backend build not found at $DEST_DIR"
  echo "Run scripts/build-backend.sh first."
  exit 1
fi

# ---- Pick the release asset for this platform ----
#
# pixi publishes one archive per target triple. Like the PyInstaller backend,
# the downloaded binary must match the machine running the build, since
# cross-compiling is not supported.
case "$(uname -s)" in
  Linux) _os="unknown-linux-musl"; _ext="tar.gz"; _bin="pixi" ;;
  Darwin) _os="apple-darwin"; _ext="tar.gz"; _bin="pixi" ;;
  MINGW* | MSYS* | CYGWIN*) _os="pc-windows-msvc"; _ext="zip"; _bin="pixi.exe" ;;
  *) echo "Error: unsupported OS $(uname -s)"; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) _arch="x86_64" ;;
  arm64 | aarch64) _arch="aarch64" ;;
  *) echo "Error: unsupported CPU architecture $(uname -m)"; exit 1 ;;
esac
ASSET="pixi-${_arch}-${_os}.${_ext}"

PIXI_VERSION="${PIXI_VERSION:-v0.83.0}"
if [[ "$PIXI_VERSION" == "latest" ]]; then
  BASE_URL="https://github.com/prefix-dev/pixi/releases/latest/download"
else
  BASE_URL="https://github.com/prefix-dev/pixi/releases/download/$PIXI_VERSION"
fi

echo "==> Downloading pixi ($PIXI_VERSION, $ASSET)..."
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

curl --fail --silent --show-error --location --retry 3 \
  --output "$TMP_DIR/$ASSET" "$BASE_URL/$ASSET"
curl --fail --silent --show-error --location --retry 3 \
  --output "$TMP_DIR/$ASSET.sha256" "$BASE_URL/$ASSET.sha256"

# ---- Verify the checksum ----
#
# The .sha256 file has the `<hash>  <filename>` format. sha256sum is available
# on Linux and in Git Bash; macOS ships shasum instead.
if command -v sha256sum >/dev/null 2>&1; then
  _sha256() { sha256sum "$1"; }
else
  _sha256() { shasum -a 256 "$1"; }
fi
_expected="$(cut -d' ' -f1 < "$TMP_DIR/$ASSET.sha256")"
_actual="$(_sha256 "$TMP_DIR/$ASSET" | cut -d' ' -f1)"
if [[ "$_expected" != "$_actual" ]]; then
  echo "Error: checksum mismatch for $ASSET (expected $_expected, got $_actual)"
  exit 1
fi

# ---- Extract the executable ----
#
# Both archives contain just the pixi executable at their root. Git Bash's tar
# cannot read zip files, so the Windows archive is extracted with Python
# (python3 is a build requirement anyway).
if [[ "$_ext" == "zip" ]]; then
  python3 -m zipfile -e "$TMP_DIR/$ASSET" "$TMP_DIR/extracted"
else
  mkdir "$TMP_DIR/extracted"
  tar -xzf "$TMP_DIR/$ASSET" -C "$TMP_DIR/extracted"
fi

cp "$TMP_DIR/extracted/$_bin" "$DEST_DIR/$_bin"
chmod +x "$DEST_DIR/$_bin"
echo "    -> resources/fractal-app-lite/$_bin ($("$DEST_DIR/$_bin" --version))"
