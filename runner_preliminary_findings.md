# `_runner.py` — Preliminary Findings (handoff)

Notes for a future planning/implementation session. **No code has been written for
the runner yet** — this captures the recommendation and the facts it rests on.

## TL;DR recommendation

- **`Project` should own state + persistence only** (dataset, workflow, the two
  histories, `max_workers`, registry sources). It already does, plus the trivial
  history mutators via `History.add(...)`.
- **A separate runner (`fractal_lite/_runner.py`) should own execution orchestration**
  and operate *on* a `Project`: run, map errors → status, format the summary, update
  `project.dataset`, and append the history record.
- Pure transforms stay where they are: `Workflow.run` / `Task.run`
  (`src/fractal_lite/_tasks.py`).

### Why not put "run" on `Project`

A real run threads four runtime concerns through `Task.run`
(`src/fractal_lite/_tasks.py:379-388`):

| param | type | nature |
|-------|------|--------|
| `cancellation` | `Cancellation` | cooperative cancel token (ephemeral) |
| `on_output` | `Callable[[str], None]` | live-log callback; backend wires it to a WebSocket (ephemeral) |
| `metrics` | `RunMetrics` | per-run progress accounting (ephemeral) |
| `max_workers` | `int` | concurrency — the *only* one that is genuine `Project` state |

Three of four are ephemeral, per-invocation, caller-supplied — they can't live on a
serializable `Project` (you can't JSON a cancel token or a socket callback). Status
mapping (`completed`/`cancelled`/`failed`) and summary formatting are orchestration,
not state. Keeping them out of `Project` preserves its clean serializability and
testability. The runner still mutates the Project it's given, so dataset + history
stay consistent (the one real benefit of "Project does it").

## What the runner consolidates

It replaces the two backend services, which today do the same orchestration twice
against `AppState` + the dataclass records:

- `src/backend/run_service.py` → `run_task(...)` (single-task run)
- `src/backend/workflow_service.py` → `run_workflow(...)` (multi-step run)
  (also holds `steps_to_workflow` / `workflow_to_payload`, which are frontend-payload
  conversion — **leave those in the backend**, they are UI-shape concerns.)

Both return a `RunResult` holder (`run_service.py:27-44`): `status`, `summary`,
`log: list[str]`, `total_seconds`, `mean_item_seconds`. Worth porting as-is (a plain
class, not a pydantic model).

### Two genuinely different run models (must preserve)

1. **Single task (`run_task`)** — *transient-filter + fold-new-images* model:
   - Deep-copy the dataset; apply transient `AttributeFilter`/`TypeFilter` to the copy
     (shared dataset's `active` flags untouched).
   - Run one task on the copy.
   - Fold **only the task's new output images** (`result.zarr_urls[n_before:]`) back
     into the shared dataset, merging `attributes`/`types` for existing URLs.
   - Summary: `"+{n_new} images ({total} total)"`.
2. **Workflow (`run_workflow`)** — *thread-through* model:
   - Thread the shared dataset through every step in `[start_task, end_task)` in order
     (input/output-types + `active` flags apply cumulatively).
   - **Replace** the shared dataset with the threaded result.
   - Summary: `"{n_steps} step(s): {n_before} → {n_after} images ({n_visible} visible)"`.

Both: wrap the run in `try/except RunCancelled` (→ status `cancelled`, summary
`"cancelled"`) and `except Exception as exc` (→ status `failed`, summary
`f"failed: {exc}"`, then re-raise), and record history on every outcome. Timing via
`time.perf_counter()`; `RunMetrics.mean_item_seconds` for avg/image.

## Proposed `_runner.py` surface (sketch — not final)

```python
def run_task(
    project: Project,
    task_name: str,
    kwargs_non_parallel: dict | None,
    kwargs_parallel: dict | None,
    filters: list[tuple[str, str]],
    type_filters: list[tuple[str, bool]],
    *,
    on_output: OnOutput | None = None,
    cancellation: Cancellation | None = None,
) -> RunResult: ...

def run_workflow(
    project: Project,
    start_task: int = 0,
    end_task: int | None = None,
    *,
    on_output: OnOutput | None = None,
    cancellation: Cancellation | None = None,
) -> RunResult: ...
```

- Takes a `Project` instead of `AppState`. Reads `project.dataset`,
  `project.workflow`, `project.max_workers`; appends to `project.sandbox_history` /
  `project.workflow_history`.
- Runtime params (`on_output`, `cancellation`) are **arguments, never stored**.
- `max_workers` is read from `project.max_workers` (no longer a parameter).
- Optional thin delegate on `Project` (`project.run_workflow(...)`) is fine *only* as a
  one-liner forwarding to the runner — keep `_project.py` from importing `_execution`.

### Mapping onto the new objects (changes vs the backend services)

- **`AppState` → `Project`**: `state.dataset` → `project.dataset`,
  `state.run_history` → `project.sandbox_history`,
  `state.workflow_history` → `project.workflow_history`,
  `int(max_workers)` → `project.max_workers`.
- **Record construction → `History.add(record)`**: drops the manual
  `index=len(...)+1` repeated at all six call sites (the container auto-assigns the
  1-based index).
- **`RunRecord` → `SandboxRunRecord`**, **`WorkflowRunRecord`** (now pydantic; fields
  line up 1:1; `filters`/`type_filters` tuples round-trip via pydantic).
- **Workflow snapshot**: backend stored `payload=workflow_to_payload(workflow)` (a
  frontend-shaped dict). The new `WorkflowRunRecord.workflow` holds a real
  `Workflow` (lossless). So the runner should set `workflow=project.workflow` (or a
  copy) instead of calling `workflow_to_payload`. Schema-strip/rehydrate is already
  handled by `Project` save/load.
- **`no dataset` guard**: `run_task`/`run_workflow` currently raise `ValueError` when
  `state.dataset is None`. With `Project`, the dataset is always present (possibly
  empty). Decide whether to keep a guard on *empty* dataset or drop it.

## Open questions for the next session

1. **Persistence cadence:** should the runner auto-`project.save()` (or
   `save_dataset` + `save_*_history`) after a run, or leave saving to the caller?
   (Backend never persisted per-run; it relied on explicit session save.)
2. **Where does `_runner.py` live** — in `fractal_lite` (domain-pure, but imports
   `_execution`, which it already does transitively) or kept in `backend`? Leaning
   `fractal_lite` since `Project`/`History` now live there and the goal is
   consolidation.
3. **`RunResult` home:** move it next to the runner; keep it a plain holder.
4. **`on_output` type:** reuse `OnOutput` from `_execution` rather than redefining
   `Callable[[str], None]`.
5. **Empty-dataset semantics** (see guard note above).
6. **Backend wiring** (separate step, out of this module's scope): `routes/run.py`,
   `routes/workflow.py`, `session.py`, and `state.py` would migrate from `AppState` +
   `*_service` to `Project` + `_runner`. The frontend-payload conversions
   (`steps_to_workflow` / `workflow_to_payload`) stay in the backend.

## Key file references

- `src/backend/run_service.py` — single-task orchestration to port.
- `src/backend/workflow_service.py:115-219` — workflow orchestration to port
  (lines 36-112 are frontend-payload conversion, **not** runner concerns).
- `src/fractal_lite/_tasks.py:379-432` — `Task.run` (the execution seam).
- `src/fractal_lite/_execution.py` — `Cancellation`, `RunMetrics`, `OnOutput`.
- `src/fractal_lite/_history.py` — `SandboxRunRecord`, `WorkflowRunRecord`,
  `History.add`.
- `src/fractal_lite/_project.py` — `Project` (state + persistence target).
