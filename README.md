# Fractal Lite

> [!WARNING]
> This project is a proof of concept (POC). It is experimental, unstable, and not intended for production use.

This is the `v3` branch of Fractal Lite: the same FastAPI + SvelteKit application as the other branches, packaged as a native desktop app with [Electron](https://www.electronjs.org/). The Python backend and SvelteKit frontend are bundled into a self-contained binary via PyInstaller, so no Python or Node.js installation is required on the user's machine.

This project contains two main components:
- fractal-lite: A minimalistic implementation of fractal core concepts (datasets, collection, tasks, workflows, projects, history) without need of a database.
- An Electron desktop app that spawns the FastAPI/uvicorn backend as a child process and points a native window at it.

## Download and install

Pre-built installers are attached to each `v3.x.y` release on the [Releases page](../../releases). Assets are named `v3.x.y-FractalLite-<os>.<ext>`, e.g. `v3.0.0-FractalLite-ubuntu-22.04.AppImage`:

| Platform | File |
|---|---|
| macOS (Apple Silicon) | `v3.x.y-FractalLite-macos-26.dmg` |
| macOS (Intel) | `v3.x.y-FractalLite-macos-15-intel.dmg` or `v3.x.y-FractalLite-macos-26-intel.dmg` |
| Windows | `v3.x.y-FractalLite-windows-2025.exe` |
| Linux | `v3.x.y-FractalLite-ubuntu-22.04.AppImage` |

None of these are code-signed, so each OS blocks them on first launch:

**macOS**

Go to **System Settings → Privacy & Security → scroll down → "Open Anyway"**.

**Linux**

The AppImage must be marked executable before running:

```bash
chmod +x v3.x.y-FractalLite-ubuntu-22.04.AppImage
./v3.x.y-FractalLite-ubuntu-22.04.AppImage
```

**Windows**

Run the installer (`.exe`). Windows Defender SmartScreen may warn about an unknown publisher — click "More info → Run anyway".

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

## Building from source

All the Electron/npm tooling lives in the `electron/` subfolder, alongside the Python/SvelteKit source at the repo root. The commands below are run from `electron/`.

### Requirements

- [Node.js](https://nodejs.org/) 22+
- [Python](https://www.python.org/) 3.12+
- [pixi](https://pixi.sh/latest/#installation) (only needed for backend-only development, see below)

### Setup

```bash
cd electron
npm install
```

### Build the Python backend and frontend

This compiles the SvelteKit frontend and packages the Python backend into a self-contained binary using PyInstaller. It only needs to be re-run when the Python code or frontend changes.

```bash
npm run build-components
```

Partial rebuilds (the backend build bakes the frontend into the PyInstaller bundle, so after a frontend change you need both):

```bash
npm run build-frontend   # rebuild only the SvelteKit frontend (scripts/build-frontend.sh)
npm run build-backend    # rebuild only the Python binary (scripts/build-backend.sh)
```

### Run in development mode

```bash
npm run dev
```

Compiles the TypeScript with hot-reload and launches Electron directly from the source tree. `npm run build-components` must have been run at least once first.

### Build a distributable

```bash
npm run package          # build for the current platform → electron/dist-electron/
npm run full-build       # build-components + package in one step
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

## Releasing a new version

Push a `v3.x.y` tag:

```bash
git tag v3.1.0
git push --tags
```

This triggers `.github/workflows/release.yml`, which builds installers for Linux, Windows and macOS (Intel and Apple Silicon) and uploads them to a GitHub Release. To trigger a build without creating a release (useful for testing), run the workflow manually from the **Actions** tab — the results are uploaded as workflow artifacts (kept for 7 days) instead.

## Development

Run these from the repo root (not `electron/`):

### Tests

```bash
pixi run -e dev test           # full test suite
pixi run -e dev test-fast      # skip slow e2e tests
```

### Linting

```bash
pixi run -e dev lint
```

## Notes

- **No database** — fractal-app-lite uses in-memory state and file-based project storage.
- **macOS code-signing** — for public distribution, uncomment the `hardenedRuntime` / `entitlements` lines in `electron/electron-builder.yml` and provide an Apple Developer certificate.
- **macOS notarization** — requires an Apple Developer account and the `CSC_LINK` / `APPLE_ID` environment variables set when running `electron-builder`.
- **`fractal-web-clone`** — the `fractal-web-clone/` directory at the repo root is created by `scripts/build-frontend.sh` (not a git submodule). Delete it and re-run the build script to refresh it.

## License

BSD 3-Clause — see [LICENSE](LICENSE).
