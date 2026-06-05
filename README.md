# Fractal Lite

> [!WARNING]
> This project is just a POC and not intended for production use.

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
