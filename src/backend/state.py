"""Shared, in-process application state for the sandbox v2 backend.

This is a single-user local desktop app, so a module-level singleton holding the
current ``Dataset`` and the session run-history is sufficient (the brief's §4). The
task registry is already a global singleton (``fractal_lite.tasks_registry``)
and is used directly. State is injected into FastAPI handlers via the ``get_state``
dependency so handlers stay testable.

Ported from the NiceGUI app's ``fractal_lite_app.state`` — the dataclasses are
unchanged so the existing session JSON (de)serialization keeps working.
"""

from dataclasses import dataclass, field

from fractal_lite import Dataset, Workflow


@dataclass
class RunRecord:
    """One entry in the session run-history."""

    index: int
    task_name: str
    # Filters applied for this run, as (attribute, value) pairs.
    filters: list[tuple[str, str]]
    kwargs_non_parallel: dict | None
    kwargs_parallel: dict | None
    # Human-readable result summary, e.g. "+8 images (42 total)".
    summary: str
    # Outcome of the run: "completed", "cancelled", or "failed".
    status: str = "completed"
    # Type filters applied for this run, as (key, value) boolean pairs.
    type_filters: list[tuple[str, bool]] = field(default_factory=list)


@dataclass
class WorkflowRunRecord:
    """One entry in the workflow run-history (the Workflow tab's counterpart to
    :class:`RunRecord`)."""

    index: int
    name: str
    # Human-readable result summary, e.g. "3 step(s): 8 → 42 images (42 visible)".
    summary: str
    # Outcome of the run: "completed", "cancelled", or "failed".
    status: str = "completed"
    # Snapshot of the editable step-list payload (``workflow_to_payload`` shape), so a
    # run can be fully restored into the editor.
    payload: dict | None = None
    # The [start, end) sub-range that was actually run (display only).
    start_task: int = 0
    end_task: int | None = None


@dataclass
class AppState:
    """Mutable session state shared across the app."""

    dataset: Dataset | None = None
    run_history: list[RunRecord] = field(default_factory=list)
    # Past workflow runs (the Workflow tab's restore-capable history).
    workflow_history: list[WorkflowRunRecord] = field(default_factory=list)
    # Max concurrent task subprocesses for the parallel phase (1 = sequential).
    max_workers: int = 1
    # The workflow being composed in the Workflow tab (the canonical Workflow;
    # the frontend mirrors it as an editable step list).
    workflow: Workflow = field(default_factory=Workflow)


# Module-level singleton for the single-user process.
app_state = AppState()


def get_state() -> AppState:
    """FastAPI dependency returning the process-wide application state."""
    return app_state
