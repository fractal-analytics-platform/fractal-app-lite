# Fractal Lite

> [!WARNING]
> This project is a proof of concept (POC). It is experimental, unstable, and not intended for production use.

This project contains two main components:
- fractal-lite: A minimalistic implementation of fractal core concepts (datasets, collection, tasks, workflows, projects, history) without need of a database.
- A desktop app built with pywebview that serves a Svelte frontend and provides native file dialogs via a Python bridge.

## Requirements

- [pixi](https://pixi.sh/latest/#installation)
- Node.js 18+ and npm

## Setup

Run these three steps once after cloning.

**1. Vendor the fractal-web component library**

```bash
pixi run clone-fractal-web
cd fractal-web-clone/components && npm install --omit=peer
```

**2. Build the frontend SPA**

```bash
pixi run build-frontend
```

## Running

Launch the native desktop window:

```bash
pixi run app
```

Or run the API server only (serves the built frontend at <http://127.0.0.1:8765>):

```bash
pixi run serve
```

To open a previously saved project:

```bash
pixi run app --open demo.flp
```

## Build executable

To generate multi-platform single executable files, run the following command **after building the frontend**:

```bash
pixi run build-executable
```

Generated executables are located in the `dist` folder.

## Running a released executable

Every `v2.x.y` tag triggers a GitHub Actions release build for Linux, Windows and
macOS (Intel and Apple Silicon). Download the asset matching your OS from the
[Releases page](../../releases) — assets are named
`v2.x.y-fractal-<os>[.exe]`, e.g. `v2.x.y-fractal-ubuntu-22.04` or
`v2.x.y-fractal-windows-2025.exe`.

**Linux**

```bash
chmod +x v2.x.y-fractal-ubuntu-22.04
./v2.x.y-fractal-ubuntu-22.04
```

**macOS**

The binary is unsigned, so Gatekeeper blocks it on first run. Remove the
quarantine attribute, then run it:

```bash
chmod +x v2.x.y-fractal-macos-26
xattr -cr v2.x.y-fractal-macos-26
./v2.x.y-fractal-macos-26
```

**Windows**

Double-click `v2.x.y-fractal-windows-2025.exe`, or run it from a terminal. The
binary is unsigned, so SmartScreen may warn on first launch — choose
**More info > Run anyway**.

To open a previously saved project, pass its directory as an argument, e.g.
`./v2.x.y-fractal-ubuntu-22.04 --open demo.flp` (same `--open` flag as `pixi run app`).

## Development

### Tests

```bash
pixi run -e dev test           # full test suite
pixi run -e dev test-fast      # skip slow e2e tests
```

### Linting

```bash
pixi run -e dev lint
```

## License

BSD 3-Clause — see [LICENSE](LICENSE).
