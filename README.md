# Fractal Lite

> [!WARNING]
> This project is a proof of concept (POC). It is experimental, unstable, and not intended for production use.

This project contains two main components:
- fractal-lite: A minimalistic implementation of fractal core concepts (datasets, collection, tasks, workflows, projects, history) without need of a database.
- A desktop app built with pywebview that serves a Svelte frontend and provides native file dialogs via a Python bridge.

## Get the executable

Fractal Lite is distributed as a single-file executable. You can either download
a pre-built one or build it yourself.

### Option 1: download a release

Pre-built executables for every `v2.x.y` release are available on the
[Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v2&expanded=true).
Download the asset matching your OS:

| OS | Asset |
| --- | --- |
| Linux (x86_64, Ubuntu 22.04 or newer) | `v2.x.y-fractal-ubuntu-22.04` |
| Windows (x86_64) | `v2.x.y-fractal-windows-2025.exe` |
| macOS, Apple Silicon (M1 or newer) | `v2.x.y-fractal-macos-26` |
| macOS, Intel, macOS 15 | `v2.x.y-fractal-macos-15-intel` |
| macOS, Intel, macOS 26 or newer | `v2.x.y-fractal-macos-26-intel` |

### Option 2: build it locally

The build produces an executable for the OS (and CPU architecture) you run it on.

**Requirements**

- [pixi](https://pixi.sh/latest/#installation)
- Node.js 18+ and npm
- git

**Steps**

From the root of the cloned repository run (on Windows, use PowerShell or Git Bash):

```bash
# 1. Vendor the fractal-web component library
pixi run clone-fractal-web
cd fractal-web-clone/components
npm install --omit=peer
cd ../..

# 2. Build the frontend
pixi run build-frontend

# 3. Build the executable
pixi run build-executable
```

The executable is written to the `dist` folder:

- Linux and macOS: `dist/fractal`
- Windows: `dist\fractal.exe`

## How to run the app

In the commands below, replace `<executable>` with the name of the file you
downloaded (e.g. `v2.x.y-fractal-ubuntu-22.04`) or with the path of the one you
built (e.g. `dist/fractal`).

### Linux

Make the file executable, then launch it:

```bash
chmod +x <executable>
./<executable>
```

### macOS

The executable is not signed, so Gatekeeper blocks it the first time. Make it
executable and remove the quarantine attribute, then launch it from a terminal:

```bash
chmod +x <executable>
xattr -cr <executable>
./<executable>
```

The `xattr` step is only needed for downloaded files.

### Windows

Double-click the `.exe` file, or launch it from a terminal:

```powershell
.\<executable>
```

The executable is not signed, so SmartScreen may show a warning the first time.
Click **More info**, then **Run anyway**. A console window with the app logs opens
next to the app window. Keep it open while you use the app.

### Open a saved project

To open a previously saved project, pass its path with `--open`:

```bash
./<executable> --open demo.flp
```

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
