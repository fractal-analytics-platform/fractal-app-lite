"""Whole-session persistence: bundle the in-memory state into one ``state.json``.

The sandbox keeps its session in memory (``state.dataset``, ``state.run_history``,
``state.max_workers``) plus the global ``tasks_registry``. This module serializes all
of that into a single JSON file so work can span multiple sittings.

A single bundled JSON is used (rather than a separate dataset CSV) because it
round-trips faithfully — embedding the ``Dataset`` as JSON preserves its ``name`` and
attribute value-types, which ``Dataset.from_csv`` cannot. This module is intentionally
UI-free so it stays importable from the API routes, the CLI and tests.

Ported unchanged from the NiceGUI app's ``fractal_lite_app.session`` except that it
targets ``backend.state`` (the new ``AppState`` singleton). The on-disk JSON shape is
identical, so sessions saved by the NiceGUI app keep loading here (the brief's §4/§6).
"""

import contextlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend.state import AppState, RunRecord, WorkflowRunRecord, app_state
from fractal_lite import Dataset, Task, Workflow, tasks_registry

# Bump when the on-disk schema changes incompatibly.
SESSION_VERSION = 1

# Cap embedded run/workflow summaries (failed runs can carry full tracebacks).
MAX_SUMMARY_CHARS = 4000


def _resolve(state: AppState | None) -> AppState:
    return state if state is not None else app_state


def _truncate_summary(summary: str) -> str:
    """Trim an over-long summary to a head+tail with an elision marker."""
    if not summary or len(summary) <= MAX_SUMMARY_CHARS:
        return summary
    head = MAX_SUMMARY_CHARS // 2
    tail = MAX_SUMMARY_CHARS - head
    omitted = len(summary) - MAX_SUMMARY_CHARS
    return f"{summary[:head]}\n... [{omitted} chars elided] ...\n{summary[-tail:]}"


def _strip_task_schemas(node: Any) -> Any:
    """Blank regenerable JSON schemas (``args_schema_*``) in a nested structure.

    Recurses through dicts/lists so it handles a serialized ``Workflow``, a single
    task dict, or a workflow-history ``payload`` snapshot. These schemas are large
    and are re-derived from each task's source on load, so persisting them only
    bloats the bundle. Setting them to ``{}`` keeps the value valid against the
    required ``dict[str, Any]`` fields, so the bundle still validates on load.
    """
    if isinstance(node, dict):
        for key in ("args_schema_parallel", "args_schema_non_parallel"):
            if key in node:
                node[key] = {}
        for value in node.values():
            _strip_task_schemas(value)
    elif isinstance(node, list):
        for item in node:
            _strip_task_schemas(item)
    return node


def session_to_dict(state: AppState | None = None) -> dict[str, Any]:
    """Serialize the session (dataset + history + settings + registry) to a dict.

    Regenerable data is omitted to keep the bundle small: the registry is stored as
    sources-only (``packages`` are rebuilt from them on load) and the large
    ``args_schema_*`` JSON schemas embedded in the workflow / history snapshots are
    blanked. Both are restored by :func:`apply_session_dict`.
    """
    state = _resolve(state)

    run_history = [asdict(record) for record in state.run_history]
    for record in run_history:
        record["summary"] = _truncate_summary(record.get("summary", ""))

    workflow_history = [asdict(record) for record in state.workflow_history]
    for record in workflow_history:
        record["summary"] = _truncate_summary(record.get("summary", ""))
        _strip_task_schemas(record.get("payload"))

    workflow = _strip_task_schemas(state.workflow.model_dump(mode="json"))

    return {
        "version": SESSION_VERSION,
        "dataset": (
            state.dataset.model_dump(mode="json") if state.dataset is not None else None
        ),
        "run_history": run_history,
        "workflow_history": workflow_history,
        "max_workers": state.max_workers,
        "registry": tasks_registry.to_sources_dict(),
        # Per-package kwargs a bare re-collection would otherwise drop.
        "package_kwargs": tasks_registry.package_kwargs(),
        "workflow": workflow,
    }


def save_session(path: str | Path, state: AppState | None = None) -> None:
    """Write the current session to ``path`` as a bundled ``state.json``."""
    Path(path).write_text(json.dumps(session_to_dict(state), indent=2))


def _record_from_dict(data: dict[str, Any]) -> RunRecord:
    return RunRecord(
        index=data["index"],
        task_name=data["task_name"],
        # JSON has no tuples; restore the (attribute, value) pairs as tuples.
        filters=[tuple(pair) for pair in data.get("filters", [])],
        kwargs_non_parallel=data.get("kwargs_non_parallel"),
        kwargs_parallel=data.get("kwargs_parallel"),
        summary=data.get("summary", ""),
        status=data.get("status", "completed"),
    )


def _workflow_record_from_dict(data: dict[str, Any]) -> WorkflowRunRecord:
    return WorkflowRunRecord(
        index=data["index"],
        name=data.get("name", ""),
        summary=data.get("summary", ""),
        status=data.get("status", "completed"),
        payload=data.get("payload"),
        start_task=data.get("start_task", 0),
        end_task=data.get("end_task"),
    )


def apply_session_dict(data: dict[str, Any], state: AppState | None = None) -> None:
    """Restore session state from a dict produced by :func:`session_to_dict`.

    Mutates ``state`` (default: the global ``app_state`` singleton) and the global
    ``tasks_registry`` in place.

    Raises:
        ValueError: If the bundle's version is not understood.
    """
    state = _resolve(state)
    version = data.get("version")
    if version != SESSION_VERSION:
        raise ValueError(
            f"Unsupported session version {version!r} (expected {SESSION_VERSION})."
        )
    dataset = data.get("dataset")
    state.dataset = Dataset.model_validate(dataset) if dataset else None
    state.run_history = [
        _record_from_dict(record) for record in data.get("run_history", [])
    ]
    # Optional (added after v1); absent in older bundles → empty history.
    state.workflow_history = [
        _workflow_record_from_dict(record)
        for record in data.get("workflow_history", [])
    ]
    state.max_workers = int(data.get("max_workers", 1))
    registry = data.get("registry")
    if registry is not None:
        tasks_registry.load_from_dict(registry)
    # Optional (added after v1); absent in older bundles → empty workflow.
    workflow = data.get("workflow")
    state.workflow = Workflow.model_validate(workflow) if workflow else Workflow()
    _rehydrate(state, data)


def _rehydrate(state: AppState, data: dict[str, Any]) -> None:
    """Rebuild data omitted from a slim bundle, in place.

    Re-collects the registry's ``packages`` from its ``sources``, re-applies any
    saved per-package kwargs, then re-resolves the current workflow's task schemas
    from the refreshed registry. Best-effort throughout: a moved or unavailable
    source must not block restoring the rest of the session (a sources-only bundle
    that fails to re-collect just leaves those tasks degraded, not the whole load).
    """
    with contextlib.suppress(Exception):
        tasks_registry.recollect_tasks()
    with contextlib.suppress(Exception):
        tasks_registry.apply_package_kwargs(data.get("package_kwargs", {}))
    _resolve_workflow_schemas(state)


def _resolve_workflow_schemas(state: AppState) -> None:
    """Overlay full task definitions (incl. schemas) from the registry onto the
    workflow's steps, matched by ``unique_id``. Steps whose task is not in the
    registry keep their blanked schemas (degraded but still loadable)."""
    resolved: list[Any] = []
    for step in state.workflow.task_list:
        if isinstance(step, Task):
            try:
                reg = tasks_registry.get_task(step.unique_id)
            except KeyError:
                reg = None
            if reg is not None:
                step = step.model_copy(
                    update={"task": reg.task, "source_info": reg.source_info}
                )
        resolved.append(step)
    state.workflow.task_list = resolved


def load_session(path: str | Path, state: AppState | None = None) -> None:
    """Read a bundled ``state.json`` from ``path`` and restore the session."""
    apply_session_dict(json.loads(Path(path).read_text()), state)
