"""Execution orchestration on a :class:`~fractal_lite._project.Project`.

This consolidates what used to be two backend services (``run_service`` and
``workflow_service``) into the module that now owns the state. The runner operates
*on* a :class:`Project`: it runs a task or a workflow, maps errors to a status,
formats the summary, mutates ``project.dataset`` and appends to the relevant history,
and returns a :class:`RunResult`. The pure transforms it builds on
(:meth:`Task.run`, :meth:`Workflow.run`) stay where they are.

Two genuinely different run models are preserved:

* **Single task** (:func:`run_task`) — *transient-filter + fold-new-images*: apply
  transient filters to a deep copy of the shared dataset, run one task on the copy,
  and fold only the task's *new* output images back into the shared dataset. The
  shared dataset's own ``active`` flags are never touched.
* **Workflow** (:func:`run_workflow`) — *thread-through*: thread the shared dataset
  through every step in ``[start, end)`` (so input-/output-types and ``active`` flags
  apply cumulatively) and *replace* the shared dataset with the threaded result.

The runner never persists: it only mutates the in-memory :class:`Project`. The caller
decides when to ``project.save()``. Runtime concerns (``on_output``, ``cancellation``)
are arguments, never stored; ``max_workers`` is read from ``project.max_workers``.
"""

import time

from fractal_lite._dataset import Dataset
from fractal_lite._execution import (
    Cancellation,
    OnOutput,
    RunCancelled,
    RunMetrics,
)
from fractal_lite._filters import AttributeFilter, TypeFilter
from fractal_lite._history import SandboxRunRecord, WorkflowRunRecord
from fractal_lite._project import Project
from fractal_lite._registry import tasks_registry
from fractal_lite._tasks import Task


class RunResult:
    """Outcome of a run (a plain holder, not a Pydantic model)."""

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
    project: Project,
    task_name: str,
    kwargs_non_parallel: dict | None,
    kwargs_parallel: dict | None,
    filters: list[tuple[str, str]],
    type_filters: list[tuple[str, bool]],
    *,
    on_output: OnOutput | None = None,
    cancellation: Cancellation | None = None,
) -> RunResult:
    """Run ``task_name`` on the project's dataset, folding new images back in.

    Mutates ``project.dataset`` and ``project.sandbox_history`` in place. Raises
    ``KeyError`` if the task is unknown.
    """
    log: list[str] = []

    def emit(line: str) -> None:
        log.append(line)
        if on_output is not None:
            on_output(line)

    # Transient filters apply to a deep copy; the shared dataset is untouched.
    applied_filters = [(a, v) for a, v in filters if a]
    applied_type_filters = [(k, v) for k, v in type_filters if k]
    working = project.dataset.model_copy(deep=True)
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
            max_workers=int(project.max_workers),
            metrics=metrics,
        )
    except RunCancelled:
        project.sandbox_history.add(
            SandboxRunRecord(
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
        project.sandbox_history.add(
            SandboxRunRecord(
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
    existing_by_url = {zu.url: zu for zu in project.dataset.zarr_urls}
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
    project.dataset = project.dataset.model_copy(
        update={"zarr_urls": list(existing_by_url.values())}
    )

    summary = f"+{len(new_images)} images ({len(project.dataset.zarr_urls)} total)"
    project.sandbox_history.add(
        SandboxRunRecord(
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


def run_workflow(
    project: Project,
    start_task: int = 0,
    end_task: int | None = None,
    *,
    on_output: OnOutput | None = None,
    cancellation: Cancellation | None = None,
) -> RunResult:
    """Run ``project.workflow`` over the dataset, threading it through each step.

    Runs steps ``[start_task, end_task)``. Mutates ``project.dataset`` (replacing it
    with the threaded result) and appends a summarizing entry to
    ``project.workflow_history``.

    Raises:
        ValueError: If the workflow has no steps to run.
    """
    workflow = project.workflow
    steps = workflow.task_list[start_task:end_task]
    if not steps:
        raise ValueError("No workflow steps to run.")

    log: list[str] = []

    def emit(line: str) -> None:
        log.append(line)
        if on_output is not None:
            on_output(line)

    n_before = len(project.dataset.zarr_urls)
    dataset: Dataset = project.dataset
    t0 = time.perf_counter()
    last_metrics: RunMetrics | None = None

    try:
        for offset, step in enumerate(steps):
            index = start_task + offset
            if isinstance(step, Task):
                emit(f"[step {index}] Running task {step.unique_id!r}")
                metrics = RunMetrics()
                dataset = step.run(
                    dataset,
                    on_output=emit,
                    cancellation=cancellation,
                    max_workers=int(project.max_workers),
                    metrics=metrics,
                )
                last_metrics = metrics
            else:
                emit(f"[step {index}] Applying filter {step.type!r}")
                dataset = step.run(dataset)
    except RunCancelled:
        emit("Workflow cancelled.")
        project.workflow_history.add(
            WorkflowRunRecord(
                name=workflow.name,
                summary="cancelled",
                status="cancelled",
                workflow=workflow.model_copy(deep=True),
                start_task=start_task,
                end_task=end_task,
            )
        )
        return RunResult("cancelled", "cancelled", log)
    except Exception as exc:
        emit(f"Workflow run failed: {exc}")
        project.workflow_history.add(
            WorkflowRunRecord(
                name=workflow.name,
                summary=f"failed: {exc}",
                status="failed",
                workflow=workflow.model_copy(deep=True),
                start_task=start_task,
                end_task=end_task,
            )
        )
        raise

    total = time.perf_counter() - t0
    project.dataset = dataset
    n_after = len(dataset.zarr_urls)
    n_visible = len([zu for zu in dataset.zarr_urls if zu.active])
    summary = (
        f"{len(steps)} step(s): {n_before} → {n_after} images ({n_visible} visible)"
    )
    project.workflow_history.add(
        WorkflowRunRecord(
            name=workflow.name,
            summary=summary,
            workflow=workflow.model_copy(deep=True),
            start_task=start_task,
            end_task=end_task,
        )
    )
    avg = last_metrics.mean_item_seconds if last_metrics else None
    emit(f"Done. {summary}. Runtime: {total:.1f}s total.")
    return RunResult(
        "completed", summary, log, total_seconds=total, mean_item_seconds=avg
    )
