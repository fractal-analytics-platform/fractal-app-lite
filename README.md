# Fractal Lite

> [!WARNING]
> This project is a proof of concept (POC). It is experimental, unstable, and not intended for production use.

This is the `v3` branch of Fractal Lite: the same FastAPI + SvelteKit application as the other branches, packaged as a native desktop app with [Electron](https://www.electronjs.org/). The Python backend and SvelteKit frontend are bundled into a self-contained binary via PyInstaller, so no Python or Node.js installation is required on the user's machine.

This project contains two main components:
- fractal-lite: A minimalistic implementation of fractal core concepts (datasets, collection, tasks, workflows, projects, history) without need of a database.
- An Electron desktop app that spawns the FastAPI/uvicorn backend as a child process and points a native window at it.

## Get the app

You can either download a pre-built installer or build it yourself.

### Option 1: download a release

Pre-built installers for every `v3.x.y` release are available on the
[Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v3&expanded=true).
Download the asset matching your OS:

| OS | Asset |
| --- | --- |
| Linux (x86_64, Ubuntu 22.04 or newer) | `v3.x.y-FractalLite-ubuntu-22.04.AppImage` |
| Windows (x86_64) | `v3.x.y-FractalLite-windows-2025.exe` |
| macOS, Apple Silicon (M1 or newer) | `v3.x.y-FractalLite-macos-26.dmg` |
| macOS, Intel, macOS 15 | `v3.x.y-FractalLite-macos-15-intel.dmg` |
| macOS, Intel, macOS 26 or newer | `v3.x.y-FractalLite-macos-26-intel.dmg` |

### Option 2: build it locally

The build produces an installer for the OS (and CPU architecture) you run it on.
Cross-compiling is not supported.

**Requirements**

- [Node.js](https://nodejs.org/) 22+ and npm
- [Python](https://www.python.org/) 3.12+, available as `python3`
- git
- bash. On Windows, use [Git Bash](https://git-scm.com/downloads/win) and make sure
  `python3 --version` prints 3.12 or newer there.

**Steps**

All the Electron/npm tooling lives in the `electron/` subfolder. From the root of
the cloned repository run:

```bash
cd electron
npm install
npm run full-build
```

`npm run full-build` builds the SvelteKit frontend, packages the Python backend with
PyInstaller, and packages everything with electron-builder. The first run takes a while.

The installer is written to `electron/dist-electron/`:

| OS | Output |
| --- | --- |
| Linux | `FractalLite-<version>-linux-x86_64.AppImage` |
| Windows | `FractalLite-<version>-win-x64.exe` |
| macOS | `FractalLite-<version>-mac-<arch>.dmg` |

## How to run the app

None of the installers are code-signed, so each OS asks for confirmation the first
time you launch the app.

### Linux

Make the AppImage executable, then launch it:

```bash
chmod +x <file>.AppImage
./<file>.AppImage
```

If it fails with an error about FUSE (`dlopen(): error loading libfuse.so.2`),
install FUSE 2:

```bash
sudo apt install libfuse2      # Ubuntu 22.04
sudo apt install libfuse2t64   # Ubuntu 24.04 or newer
```

### macOS

1. Open the `.dmg` file and drag **Fractal Lite** into the **Applications** folder.
2. Launch **Fractal Lite** from Applications. macOS blocks it the first time.
3. Go to **System Settings → Privacy & Security**, scroll down and click **Open Anyway**.

If macOS says the app "is damaged and can't be opened", remove the quarantine
attribute and try again:

```bash
xattr -cr "/Applications/Fractal Lite.app"
```

### Windows

1. Run the installer (`.exe`). Windows Defender SmartScreen may warn about an
   unknown publisher: click **More info**, then **Run anyway**.
2. The installer installs the app for the current user and starts it.
3. Afterwards, launch **Fractal Lite** from the Start menu or the desktop shortcut.

## How it works

When you launch Fractal Lite, Electron starts the Python server (`fractal-app-lite`) in the background, waits for it to be ready, then opens a window pointing at it. The UI and application logic live entirely inside the Python/SvelteKit bundle — Electron is only the container.

```
Electron (main process)
  │
  ├─ spawns ──► fractal-app-lite  (Python / uvicorn / FastAPI)
  │                │
  │                ├─ GET /api/*   → Python handlers
  │                └─ GET /*       → static SvelteKit frontend
  │
  └─ opens ───► BrowserWindow → http://127.0.0.1:<random port>
```

The port is chosen randomly at startup, so there are no conflicts with other services.

See `electron/documentation.md` for the full build/packaging pipeline and `electron/CLAUDE.md` for an architecture overview.

## Development

Unless noted otherwise, run these from the `electron/` folder, after `npm install`.

### Run in development mode

```bash
npm run build-components   # build frontend + Python backend (needed at least once)
npm run dev
```

`npm run dev` compiles the TypeScript with hot-reload and launches Electron directly
from the source tree.

To rebuild only one part (the backend build bakes the frontend into the PyInstaller bundle, so after a frontend change you need both):

```bash
npm run build-frontend   # rebuild only the SvelteKit frontend (scripts/build-frontend.sh)
npm run build-backend    # rebuild only the Python binary (scripts/build-backend.sh)
```

### Other useful commands

```bash
npm run typecheck        # type-check the main process TypeScript (no output = clean)
npm run build            # compile TypeScript only → out/
```

### Backend-only development

The Python backend can still be run standalone (without Electron) via pixi, e.g. for iterating on the API without rebuilding the desktop shell. Run this from the repo root (not `electron/`):

```bash
pixi run serve   # runs uvicorn directly, serving the built frontend if present
```

### Tests

Run these from the repo root (not `electron/`):

```bash
pixi run -e dev test           # full test suite
pixi run -e dev test-fast      # skip slow e2e tests
```

### Linting

From the repo root:

```bash
pixi run -e dev lint
```

## Releasing a new version

Push a `v3.x.y` tag:

```bash
git tag v3.1.0
git push --tags
```

This triggers `.github/workflows/release.yml`, which builds installers for Linux, Windows and macOS (Intel and Apple Silicon) and uploads them to a GitHub Release. To trigger a build without creating a release (useful for testing), run the workflow manually from the **Actions** tab — the results are uploaded as workflow artifacts (kept for 7 days) instead.

## Notes

- **No database** — fractal-app-lite uses in-memory state and file-based project storage.
- **macOS code-signing** — for public distribution, uncomment the `hardenedRuntime` / `entitlements` lines in `electron/electron-builder.yml` and provide an Apple Developer certificate.
- **macOS notarization** — requires an Apple Developer account and the `CSC_LINK` / `APPLE_ID` environment variables set when running `electron-builder`.
- **`fractal-web-clone`** — the `fractal-web-clone/` directory at the repo root is created by `scripts/build-frontend.sh` (not a git submodule). Delete it and re-run the build script to refresh it.

## License

BSD 3-Clause — see [LICENSE](LICENSE).
