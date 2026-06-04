"""Interactive single-task run logic, ported UI-free from the NiceGUI ``sandbox_tab``.

This preserves the original run model exactly (the brief's locked-in decision): apply
transient filters to a deep copy of the shared dataset, run one task, fold only the
task's *new* output images back into the shared dataset, and record the run in history.
The shared dataset's own ``hidden`` flags are never touched here.

The function is synchronous and accepts an ``on_output`` callback and a
``Cancellation`` token — the same seams the core ``task.run`` already uses — so a later
phase can stream logs over a WebSocket without touching this logic.
"""

import time
from collections.abc import Callable

from backend.state import AppState, RunRecord
from fractal_lite import (
    Cancellation,
    Dataset,
    RunCancelled,
    RunMetrics,
    tasks_registry,
)
from fractal_lite._filters import AttributeFilter, TypeFilter


class RunResult:
    """Outcome of :func:`run_task` (a plain holder, not a Pydantic model)."""

    def __init__(
        self,
        status: str,
        summary: str,
        log: list[str],
        *,
        total_seconds: float | None = None,
        mean_item_seconds: float | None = None,
    ) -> None:
        self.status = status
        self.summary = summary
        self.log = log
        # Per-run runtime metrics (None when not measured, e.g. on cancel).
        self.total_seconds = total_seconds
        self.mean_item_seconds = mean_item_seconds


def run_task(
    state: AppState,
    task_name: str,
    kwargs_non_parallel: dict | None,
    kwargs_parallel: dict | None,
    filters: list[tuple[str, str]],
    type_filters: list[tuple[str, bool]],
    max_workers: int,
    *,
    on_output: Callable[[str], None] | None = None,
    cancellation: Cancellation | None = None,
) -> RunResult:
    """Run ``task_name`` on the shared dataset, folding new images back in.

    Mutates ``state.dataset`` and ``state.run_history`` in place. Raises
    ``ValueError`` if there is no dataset or the task is unknown.
    """
    if state.dataset is None:
        raise ValueError("No dataset loaded. Create or load a dataset first.")

    log: list[str] = []

    def emit(line: str) -> None:
        log.append(line)
        if on_output is not None:
            on_output(line)

    # Transient filters apply to a deep copy; the shared dataset is untouched.
    applied_filters = [(a, v) for a, v in filters if a]
    applied_type_filters = [(k, v) for k, v in type_filters if k]
    working = state.dataset.model_copy(deep=True)
    for attr, val in applied_filters:
        working = AttributeFilter(attribute=attr, value=val).run(working)
    for key, val in applied_type_filters:
        working = TypeFilter(key=key, value=val).run(working)
    n_before = len(working.zarr_urls)

    task = tasks_registry.get_task(task_name).model_copy(
        update={
            "kwargs_non_parallel": kwargs_non_parallel or None,
            "kwargs_parallel": kwargs_parallel or None,
        }
    )

    emit(f"Running {task_name!r} on {n_before} input image(s) → {working.zarr_dir}")
    metrics = RunMetrics()
    t0 = time.perf_counter()
    try:
        result: Dataset = task.run(
            working,
            on_output=emit,
            cancellation=cancellation,
            max_workers=int(max_workers),
            metrics=metrics,
        )
    except RunCancelled:
        state.run_history.append(
            RunRecord(
                index=len(state.run_history) + 1,
                task_name=task_name,
                filters=applied_filters,
                type_filters=applied_type_filters,
                kwargs_non_parallel=kwargs_non_parallel or None,
                kwargs_parallel=kwargs_parallel or None,
                summary="cancelled",
                status="cancelled",
            )
        )
        emit("Run cancelled.")
        return RunResult("cancelled", "cancelled", log)
    except Exception as exc:
        state.run_history.append(
            RunRecord(
                index=len(state.run_history) + 1,
                task_name=task_name,
                filters=applied_filters,
                type_filters=applied_type_filters,
                kwargs_non_parallel=kwargs_non_parallel or None,
                kwargs_parallel=kwargs_parallel or None,
                summary=f"failed: {exc}",
                status="failed",
            )
        )
        emit(f"Run failed: {exc}")
        raise

    total = time.perf_counter() - t0

    # Only the task's new output images fold back; the filtered copy is discarded.
    new_images = result.zarr_urls[n_before:]
    existing_by_url = {zu.url: zu for zu in state.dataset.zarr_urls}
    for img in new_images:
        if img.url in existing_by_url:
            old = existing_by_url[img.url]
            existing_by_url[img.url] = old.model_copy(
                update={
                    "attributes": {**old.attributes, **img.attributes},
                    "types": {**old.types, **img.types},
                }
            )
        else:
            existing_by_url[img.url] = img
    state.dataset = state.dataset.model_copy(
        update={"zarr_urls": list(existing_by_url.values())}
    )

    summary = f"+{len(new_images)} images ({len(state.dataset.zarr_urls)} total)"
    state.run_history.append(
        RunRecord(
            index=len(state.run_history) + 1,
            task_name=task_name,
            filters=applied_filters,
            type_filters=applied_type_filters,
            kwargs_non_parallel=kwargs_non_parallel or None,
            kwargs_parallel=kwargs_parallel or None,
            summary=summary,
        )
    )
    avg = metrics.mean_item_seconds
    if avg is not None:
        emit(f"Done. {summary}. Runtime: {total:.1f}s total, {avg:.1f}s avg/image.")
    else:
        emit(f"Done. {summary}. Runtime: {total:.1f}s total.")
    return RunResult(
        "completed", summary, log, total_seconds=total, mean_item_seconds=avg
    )
