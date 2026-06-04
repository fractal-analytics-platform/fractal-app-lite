# Fractal Tasks Sandbox v2 — FastAPI + Svelte

A single-user local desktop port of the NiceGUI Fractal Tasks Sandbox, with an explicit
**Svelte frontend** and a **FastAPI backend**, packaged as a native window via
**pywebview**. The compute core (`fractal_lite/`) is carried over unchanged;
schema-driven argument forms are rendered by the `fractal-components` `JSchema` component
reused from `fractal-web`.

See `migration-brief-fastapi-svelte.md` (one level up) for the full rationale.

## Layout

```
app/
  fractal_lite/   # compute core, copied UNCHANGED from the NiceGUI app
  backend/                 # FastAPI app
    main.py                #   app factory: API routers + static frontend, lifespan collect
    shell.py               #   pywebview entrypoint (uvicorn thread + native window)
    state.py               #   AppState singleton + get_state() dependency
    session.py             #   bundled JSON session persistence (reused as-is)
    run_service.py         #   interactive single-task run (ported UI-free)
    schemas.py             #   API request/response models
    routes/                #   tasks, dataset, session, run
  frontend/                # SvelteKit static SPA (Svelte 5)
    src/routes/+page.svelte#   task picker + JSchema form + run
    build/                 #   static output, served by FastAPI (after `npm run build`)
  tests/                   # backend API smoke tests
  pyproject.toml           # pixi-managed
```

## Setup & run

This milestone covers the scaffold + the schema-form vertical slice (carve out core →
FastAPI → pywebview → one task form end-to-end). Three one-time setup steps, then launch.

1. **Install the JSchema component's deps in the local fractal-web clone.** The frontend
   aliases `fractal-components` to the clone's source (pinned at tag **v1.27.11**); the
   aliased source resolves its own runtime deps from that dir. `node_modules` is
   gitignored there, so the clone's source stays pristine.
   ```bash
   cd fractal-web-clone/components && npm install --omit=peer
   ```

2. **Build the frontend** (outputs to `frontend/build/`, which FastAPI serves):
   ```bash
   cd frontend && npm install && npm run build
   ```

3. **Create the backend env** (pixi):
   ```bash
   pixi install
   ```

4. **Launch the native desktop app:**
   ```bash
   pixi run app           # == python -m backend.shell
   ```
   Or run just the API server (serves the built frontend at http://127.0.0.1:8765):
   ```bash
   pixi run serve
   ```

## Verify

- **Backend API:** `pixi run -e dev test` runs `tests/test_api_smoke.py` (lists tasks,
  fetches a Pydantic-v2 schema, dataset/session round-trip, run-without-dataset → 400).
- **End-to-end form run:** launch `pixi run app`, set a dataset (name + `zarr_dir`),
  pick a task, fill the `JSchema` form, and click **Run**. The backend executes the task
  in its isolated pixi env and folds new images into the shared dataset — matching the
  NiceGUI app's behavior for the same inputs.

## Feature parity (phases 5–6 complete)

Full parity with the NiceGUI app is implemented — see `FEATURE_PARITY.md`. Highlights:

- **Three-tab shell** (Dataset / Tasks Sandbox / Task Management) with a header carrying
  session **Save/Load**, a **dark-mode** toggle, and the logo.
- **Dataset tab**: create (browse dir + mkdir), CSV load/save, full image table
  (dynamic attribute columns, counts, search, pagination), per-row **open-in-napari**.
- **Tasks Sandbox**: transient filters + **live preview**, **WebSocket** live-log
  streaming with **Cancel**, max-workers, Log↔Dataset output toggle, run **history +
  Restore**, **Export/Import params**, structured runtime metrics.
- **Task Management**: register from directory/tarball, tasks table + details panel
  (docs markdown + arg schemas), registry save/load.
- **Native file dialogs** via a pywebview bridge (`backend/fs.py`), with a typed-path
  modal fallback in browser/`serve` mode.
- **`--resume state.json`** launch flag in `backend/shell.py`.
