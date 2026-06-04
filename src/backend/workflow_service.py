"""Workflow composition + execution, the multi-step counterpart to ``run_service``.

Two halves:

* **Conversion** between the frontend's editable step list (``WorkflowPayload``) and the
  canonical :class:`~fractal_lite.Workflow` held in :class:`AppState`. Task
  steps are resolved against the global ``tasks_registry`` by ``unique_id`` (the same
  lookup ``run_service`` uses); filter steps map to ``AttributeFilter``/``TypeFilter``.

* **Execution** (:func:`run_workflow`). Unlike ``run_service.run_task`` — which runs one
  task in isolation and folds only *new* images back into a deep copy — a workflow
  threads the shared dataset through every step in order, so ``Task.run`` applies input-
  /output-types and ``hidden`` flags cumulatively. The shared ``state.dataset`` is
  therefore *replaced* with the threaded result. Supports running a sub-range
  ``[start, end)`` so a later step can be re-run without redoing the converters.
"""

import time
from collections.abc import Callable

from backend.run_service import RunResult
from backend.schemas import WorkflowPayload
from backend.state import AppState, WorkflowRunRecord
from fractal_lite import (
    Cancellation,
    Dataset,
    RunCancelled,
    RunMetrics,
    Workflow,
    tasks_registry,
)
from fractal_lite._filters import AttributeFilter, Filter, TypeFilter
from fractal_lite._tasks import Task


def steps_to_workflow(payload: WorkflowPayload) -> Workflow:
    """Build a canonical :class:`Workflow` from the frontend's step list.

    Raises:
        KeyError: If a task step references a task not in the registry.
        ValueError: If a step is malformed (e.g. a task step with no ``task_name``).
    """
    task_list: list[Task | Filter] = []
    for i, step in enumerate(payload.steps):
        if step.kind == "task":
            if not step.task_name:
                raise ValueError(f"Step {i}: task step is missing 'task_name'.")
            task = tasks_registry.get_task(step.task_name).model_copy(
                update={
                    "kwargs_non_parallel": step.kwargs_non_parallel or None,
                    "kwargs_parallel": step.kwargs_parallel or None,
                }
            )
            task_list.append(task)
        elif step.kind == "filter":
            if step.filter_type == "attribute":
                task_list.append(
                    AttributeFilter(
                        attribute=step.attribute or "", value=str(step.value or "")
                    )
                )
            elif step.filter_type == "type":
                task_list.append(TypeFilter(key=step.key or "", value=bool(step.value)))
            else:
                raise ValueError(f"Step {i}: unknown filter_type {step.filter_type!r}.")
        else:  # pragma: no cover - guarded by the Literal type
            raise ValueError(f"Step {i}: unknown step kind {step.kind!r}.")
    return Workflow(
        name=payload.name, description=payload.description, task_list=task_list
    )


def workflow_to_payload(workflow: Workflow) -> dict:
    """Serialize a :class:`Workflow` to the frontend step-list shape.

    The inverse of :func:`steps_to_workflow`. Tasks are referenced by ``unique_id`` so
    the frontend can re-select them; filters carry their attribute/key + value.
    """
    steps: list[dict] = []
    for step in workflow.task_list:
        if isinstance(step, Task):
            steps.append(
                {
                    "kind": "task",
                    "task_name": step.unique_id,
                    "kwargs_non_parallel": step.kwargs_non_parallel,
                    "kwargs_parallel": step.kwargs_parallel,
                }
            )
        elif isinstance(step, AttributeFilter):
            steps.append(
                {
                    "kind": "filter",
                    "filter_type": "attribute",
                    "attribute": step.attribute,
                    "value": step.value,
                }
            )
        elif isinstance(step, TypeFilter):
            steps.append(
                {
                    "kind": "filter",
                    "filter_type": "type",
                    "key": step.key,
                    "value": step.value,
                }
            )
    return {
        "name": workflow.name,
        "description": workflow.description,
        "steps": steps,
    }


def run_workflow(
    state: AppState,
    start_task: int = 0,
    end_task: int | None = None,
    max_workers: int = 1,
    *,
    on_output: Callable[[str], None] | None = None,
    cancellation: Cancellation | None = None,
) -> RunResult:
    """Run ``state.workflow`` over the shared dataset, threading it through each step.

    Runs steps ``[start_task, end_task)``. Mutates ``state.dataset`` (replacing it with
    the threaded result) and appends a summarizing entry to ``state.run_history``.

    Raises:
        ValueError: If there is no dataset or the workflow has no steps to run.
    """
    if state.dataset is None:
        raise ValueError("No dataset loaded. Create or load a dataset first.")

    workflow = state.workflow
    steps = workflow.task_list[start_task:end_task]
    if not steps:
        raise ValueError("No workflow steps to run.")

    log: list[str] = []

    def emit(line: str) -> None:
        log.append(line)
        if on_output is not None:
            on_output(line)

    n_before = len(state.dataset.zarr_urls)
    dataset: Dataset = state.dataset
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
                    max_workers=int(max_workers),
                    metrics=metrics,
                )
                last_metrics = metrics
            else:
                emit(f"[step {index}] Applying filter {step.type!r}")
                dataset = step.run(dataset)
    except RunCancelled:
        emit("Workflow cancelled.")
        state.workflow_history.append(
            WorkflowRunRecord(
                index=len(state.workflow_history) + 1,
                name=workflow.name,
                summary="cancelled",
                status="cancelled",
                payload=workflow_to_payload(workflow),
                start_task=start_task,
                end_task=end_task,
            )
        )
        return RunResult("cancelled", "cancelled", log)
    except Exception as exc:
        emit(f"Workflow run failed: {exc}")
        state.workflow_history.append(
            WorkflowRunRecord(
                index=len(state.workflow_history) + 1,
                name=workflow.name,
                summary=f"failed: {exc}",
                status="failed",
                payload=workflow_to_payload(workflow),
                start_task=start_task,
                end_task=end_task,
            )
        )
        raise

    total = time.perf_counter() - t0
    state.dataset = dataset
    n_after = len(dataset.zarr_urls)
    n_visible = len([zu for zu in dataset.zarr_urls if not zu.hidden])
    summary = (
        f"{len(steps)} step(s): {n_before} → {n_after} images ({n_visible} visible)"
    )
    state.workflow_history.append(
        WorkflowRunRecord(
            index=len(state.workflow_history) + 1,
            name=workflow.name,
            summary=summary,
            payload=workflow_to_payload(workflow),
            start_task=start_task,
            end_task=end_task,
        )
    )
    avg = last_metrics.mean_item_seconds if last_metrics else None
    emit(f"Done. {summary}. Runtime: {total:.1f}s total.")
    return RunResult(
        "completed", summary, log, total_seconds=total, mean_item_seconds=avg
    )
