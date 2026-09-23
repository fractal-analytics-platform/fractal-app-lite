#!/usr/bin/env bash
# Builds the Python backend of fractal-app-lite — packaged by PyInstaller into
# a self-contained directory (fractal-app-lite + all its Python dependencies)
# so it can run on any machine without Python installed.
#
# Source: src/  (this repo)
# Output: resources/fractal-app-lite/
#
# electron-builder copies the output directory into the packaged app bundle.
# The compiled SvelteKit frontend is baked into the bundle via --add-data, so
# scripts/build-frontend.sh must have been run first.
#
# Usage:
#   bash scripts/build-backend.sh
set -euo pipefail

# Absolute paths resolved from the location of this script, so it works
# regardless of which directory you call it from. ELECTRON_ROOT is the
# electron/ subfolder this script is part of (electron-builder's output goes
# under here); PROJECT_ROOT is the repo root one level up, where the
# Python/SvelteKit source (src/, pyproject.toml) lives.
ELECTRON_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ROOT="$(cd "$ELECTRON_ROOT/.." && pwd)"
RESOURCES_DIR="$ELECTRON_ROOT/resources"

# ---- Backend → PyInstaller onedir binary ----
#
# PyInstaller analyses the Python source, traces all imports, and assembles
# a self-contained directory (--onedir) containing:
#   - The fractal-app-lite executable
#   - A full Python runtime
#   - All imported packages (uvicorn, fastapi, pydantic, ngio, polars, …)
#   - The compiled SvelteKit static files (bundled in via --add-data)
#
# The result can run on any compatible OS without Python installed.
# We use --onedir (a directory) rather than --onefile (a single compressed
# binary) because --onefile must unpack itself to a temp directory on every
# launch, which adds noticeable startup delay. --onedir unpacks nothing —
# the files are already on disk.
echo "==> Building fractal-app-lite with PyInstaller..."

# The frontend build must exist before we run PyInstaller, because PyInstaller
# copies it into the bundle via --add-data. If the frontend has not been built
# yet, bail out with a clear error.
FRONTEND_BUILD="$PROJECT_ROOT/src/frontend/build"
if [[ ! -d "$FRONTEND_BUILD" ]]; then
  echo "Error: frontend build not found at $FRONTEND_BUILD"
  echo "Run scripts/build-frontend.sh first."
  exit 1
fi

# All PyInstaller outputs (spec file, build cache, dist output) go into a
# temporary directory outside the repo working tree, so it is never touched.
# The trap deletes the temp dir and any stray .spec files that PyInstaller
# might drop in the repo root, regardless of whether the build succeeds or
# fails.
BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"; rm -f "$PROJECT_ROOT"/*.spec' EXIT

# ---- Custom entry point ----
#
# The original fractal-app-lite was designed to be launched as a standalone
# desktop app using pywebview (a native window). Its entry point (shell.py)
# opens a pywebview window, which we don't want — Electron's BrowserWindow
# is our window.
#
# We write a replacement entry point that simply starts the uvicorn HTTP
# server on the port passed by Electron, with no GUI. The host is always
# loopback — the server must not be reachable from the network. This file
# lives outside the repo so it doesn't dirty the working tree.
cat > "$BUILD_DIR/_electron_entry.py" << 'PYEOF'
import argparse

import uvicorn

from backend.main import app

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=8765)
args, _ = parser.parse_known_args()

uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='info')
PYEOF

# ---- --add-data argument (cross-platform) ----
#
# --add-data tells PyInstaller to copy the compiled SvelteKit files into the
# bundle at _internal/frontend/build/. FastAPI then serves them at runtime.
# The format is "source:destination" on Linux/macOS and "source;destination"
# on Windows.
#
# On Windows under Git Bash / MSYS2, there is an extra complication: MSYS2
# automatically converts POSIX-style paths in arguments passed to Windows
# executables. The colon separator in "source:dest" collides with drive-letter
# syntax (C:\...), so MSYS2 mangles it — "/d/a/.../build" becomes
# "\d\a\...\build" (wrong drive letter) instead of "D:\a\...\build". To avoid
# this: use cygpath to convert the source path to a native Windows path, and
# use ";" as the separator so MSYS2 does not touch the argument at all.
if command -v cygpath >/dev/null 2>&1; then
  _frontend_native="$(cygpath -w "$PROJECT_ROOT/src/frontend/build")"
  _add_data="${_frontend_native};frontend/build"
else
  _add_data="$PROJECT_ROOT/src/frontend/build:frontend/build"
fi

# cd into the repo root so that `pip install .` finds pyproject.toml and
# installs fractal-app-lite together with all its declared dependencies.
# All PyInstaller output paths are absolute, so nothing gets written here.
cd "$PROJECT_ROOT"

# Create an isolated virtual environment in the temp dir so we don't pollute
# the system Python. Then install the project and PyInstaller into it.
# `pip install .` reads pyproject.toml and installs fractal-app-lite plus
# every package it depends on (uvicorn, fastapi, ngio, polars, …).
python3 -m venv "$BUILD_DIR/venv"
if [[ -d "$BUILD_DIR/venv/Scripts" ]]; then
  VENV_PYTHON="$BUILD_DIR/venv/Scripts/python"  # Windows (Git Bash)
else
  VENV_PYTHON="$BUILD_DIR/venv/bin/python"       # Linux / macOS
fi
"$VENV_PYTHON" -m pip install --quiet . pyinstaller websockets

# On macOS, tell PyInstaller which CPU architecture to target. Without this,
# if the system Python is a "universal2" binary (supports both arm64 and
# x86_64), PyInstaller may produce a universal2 bundle that doesn't work
# correctly on the current machine. uname -m returns "arm64" or "x86_64".
PYINSTALLER_ARCH_ARGS=()
if [[ "$(uname -s)" == "Darwin" ]]; then
  PYINSTALLER_ARCH_ARGS=(--target-arch "$(uname -m)")
fi

# --collect-all forces PyInstaller to include the entire package directory,
# not just the files it detects through static import analysis. Some packages
# (uvicorn, fastapi) load plugins and middleware dynamically at runtime using
# importlib or entry_points — those dynamic imports are invisible to static
# analysis and would be silently missing from the bundle without --collect-all.
#
# numcodecs and zarr call importlib.metadata.version() on themselves at import
# time, so their dist-info metadata must be bundled too (--collect-all copies
# it). Without it the backend crashes with PackageNotFoundError on startup.
#
# --exclude-module drops packages from the original pywebview-based entry
# point. They are declared as optional dependencies so PyInstaller's analysis
# would pull them in; excluding them keeps the bundle smaller.
#
# --paths adds src/ to the Python path so that "from backend.main import app"
# in our entry point resolves correctly.
echo "==> Running PyInstaller..."
"$VENV_PYTHON" -m PyInstaller \
  --onedir \
  --name fractal-app-lite \
  --clean \
  --noconfirm \
  --specpath "$BUILD_DIR" \
  --workpath "$BUILD_DIR/build" \
  --distpath "$BUILD_DIR/dist" \
  --add-data "$_add_data" \
  --collect-all backend \
  --collect-all fractal_lite \
  --collect-all uvicorn \
  --collect-all websockets \
  --collect-all fastapi \
  --collect-all pydantic \
  --collect-all ngio \
  --collect-all polars \
  --collect-all zarr \
  --collect-all numcodecs \
  --exclude-module webview \
  --exclude-module PyQt6 \
  --exclude-module PyQt5 \
  --paths "$PROJECT_ROOT/src" \
  "${PYINSTALLER_ARCH_ARGS[@]}" \
  "$BUILD_DIR/_electron_entry.py"

mkdir -p "$RESOURCES_DIR"
# Remove any previous build before copying so we don't end up with a mix of
# old and new files if the directory structure changes between builds.
rm -rf "$RESOURCES_DIR/fractal-app-lite"
cp -r "$BUILD_DIR/dist/fractal-app-lite" "$RESOURCES_DIR/fractal-app-lite"
echo "    → resources/fractal-app-lite/"
# The trap fires on exit, deleting BUILD_DIR and any stray .spec files.
