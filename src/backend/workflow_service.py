"""Conversion between the frontend's editable step list and the canonical Workflow.

Execution now lives in :func:`fractal_lite.run_workflow` (operating on a
:class:`~fractal_lite.Project`); this module keeps only the frontend↔canonical
bridge, which has no equivalent in ``fractal_lite``. Task steps are resolved against
the global ``tasks_registry`` by ``unique_id`` (the same lookup the runner uses);
filter steps map to ``AttributeFilter``/``TypeFilter``.
"""

from backend.schemas import WorkflowPayload
from fractal_lite import Workflow, tasks_registry
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
