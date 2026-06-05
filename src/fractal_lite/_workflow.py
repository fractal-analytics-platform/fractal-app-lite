import json
from typing import Any

from pydantic import BaseModel, Field

from fractal_lite._collect import _normalize_version
from fractal_lite._dataset import Dataset
from fractal_lite._filters import Filter
from fractal_lite._package_index import find_package
from fractal_lite._registry import TasksRegistry
from fractal_lite._tasks import Task

# Regenerable JSON schemas embedded in each task; large and re-derivable from the
# task's source, so they are blanked before persisting and rebuilt on load.
_SCHEMA_KEYS = ("args_schema_parallel", "args_schema_non_parallel")


def strip_task_schemas(node: Any) -> Any:
    """Blank regenerable ``args_schema_*`` schemas in a nested structure, in place.

    Recurses through dicts/lists so it handles a serialized :class:`Workflow`, a
    single task dict, or any snapshot embedding tasks. These schemas are large and
    are re-derived from each task's source on load (see
    :meth:`Workflow.resolve_schemas`), so persisting them only bloats the file.
    Setting them to ``{}`` keeps the value valid against the required
    ``dict[str, Any]`` fields, so the data still validates on load. Returns
    ``node`` for convenience.
    """
    if isinstance(node, dict):
        for key in _SCHEMA_KEYS:
            if key in node:
                node[key] = {}
        for value in node.values():
            strip_task_schemas(value)
    elif isinstance(node, list):
        for item in node:
            strip_task_schemas(item)
    return node


def _resolve_task(
    pkg_name: str, version: str | None, name: str, registry: TasksRegistry
) -> Task:
    """Find a registered :class:`Task` matching ``name``/``version``.

    The Fractal format identifies tasks only by ``pkg_name``/``version``/``name``,
    so reconstruction works by lookup: first against the already-collected
    ``registry``, then — failing that — by collecting the matching GitHub release
    for ``pkg_name`` (looked up in the curated package index).

    Raises:
        ValueError: If the package is not in the index, or the name/version
            cannot be found even after collection.
    """
    norm = _normalize_version(version) if version else None

    def find_in_registry() -> Task | None:
        for task in registry.tasks:
            if task.name != name:
                continue
            if norm is None or _normalize_version(task.version or "") == norm:
                return task
        return None

    found = find_in_registry()
    if found is not None:
        return found

    entry = find_package(pkg_name)
    if entry is None:
        raise ValueError(
            f"Cannot resolve task {name!r}: package {pkg_name!r} is not in the "
            "package index."
        )

    # Use the workflow's version as the release tag; GitHub tags are sometimes
    # 'v'-prefixed, so retry with that form before giving up.
    tags_to_try: list[str | None] = [version] if version else [None]
    if version and not version.startswith("v"):
        tags_to_try.append(f"v{version}")
    last_err: Exception | None = None
    for tag in tags_to_try:
        try:
            registry.collect_from_gitrelease(entry.repo_url, tag=tag, overwrite=True)
            break
        except Exception as err:  # try the next tag form
            last_err = err

    found = find_in_registry()
    if found is None:
        raise ValueError(
            f"Cannot resolve task {name!r} (pkg {pkg_name!r}, version {version!r}) "
            f"after collecting from {entry.repo_url}: {last_err}"
        )
    return found


class Workflow(BaseModel):
    name: str = "Unnamed Workflow"
    description: str | None = None
    task_list: list[Task | Filter] = Field(default_factory=list)

    def add_step(self, step: Task | Filter) -> None:
        """Add a step to the workflow. Steps are run in the order they are added."""
        self.task_list.append(step)

    def run(
        self, dataset: Dataset, start_task: int = 0, end_task: int | None = None
    ) -> Dataset:
        """Run the workflow on a dataset,
        from start_task (inclusive) to end_task (exclusive).
        """
        # Both ``Task.run`` and ``Filter.run`` are ``Dataset -> Dataset`` and
        # ``Task.run`` already enforces input-/output-types, so a step behaves
        # identically here and run in isolation.
        for step in self.task_list[start_task:end_task]:
            dataset = step.run(dataset)
        return dataset

    # --- Plain (lossless) JSON round-trip ----------------------------------

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the full workflow to JSON via Pydantic (lossless)."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, data: str) -> "Workflow":
        """Reconstruct a workflow from :meth:`to_json` output (lossless)."""
        return cls.model_validate_json(data)

    def resolve_schemas(self, registry: TasksRegistry) -> "Workflow":
        """Return a copy with each :class:`Task` step's full definition (incl. the
        ``args_schema_*`` blanked by :func:`strip_task_schemas`) overlaid from
        ``registry``, matched by ``unique_id``.

        Steps whose task is not in the registry are kept unchanged (degraded but
        still usable). :class:`Filter` steps carry no schemas and pass through.
        """
        resolved: list[Task | Filter] = []
        for step in self.task_list:
            if isinstance(step, Task):
                try:
                    reg = registry.get_task(step.unique_id)
                except KeyError:
                    reg = None
                if reg is not None:
                    step = step.model_copy(
                        update={"task": reg.task, "source_info": reg.source_info}
                    )
            resolved.append(step)
        return self.model_copy(update={"task_list": resolved})

    # --- Fractal export format ---------------------------------------------

    def to_fractal_dict(self) -> dict[str, Any]:
        """Serialize to Fractal's workflow-export shape.

        This is lossy: :class:`Filter` steps have no Fractal equivalent and are
        dropped, and each task is referenced only by ``pkg_name``/``version``/
        ``name``. ``type_filters``/``description``/``alias`` are always emitted
        empty to match the format.
        """
        task_list = []
        for step in self.task_list:
            if not isinstance(step, Task):
                continue  # filters are not part of the Fractal format
            inner = step.task
            task_list.append(
                {
                    "meta_non_parallel": getattr(inner, "meta_non_parallel", None),
                    "meta_parallel": getattr(inner, "meta_parallel", None),
                    "args_non_parallel": step.kwargs_non_parallel,
                    "args_parallel": step.kwargs_parallel,
                    "type_filters": {},
                    "description": None,
                    "alias": None,
                    "task": {
                        "pkg_name": step.pkg_name,
                        "version": step.version,
                        "name": step.name,
                    },
                }
            )
        return {
            "name": self.name,
            "description": self.description,
            "task_list": task_list,
        }

    def to_fractal_json(self, *, indent: int = 2) -> str:
        """Serialize to a Fractal workflow-export JSON string."""
        return json.dumps(self.to_fractal_dict(), indent=indent)

    @classmethod
    def from_fractal_dict(
        cls, data: dict[str, Any], registry: TasksRegistry
    ) -> "Workflow":
        """Reconstruct a workflow from Fractal's workflow-export shape.

        Each entry's task is resolved via :func:`_resolve_task` (lookup against
        ``registry``, auto-collecting from the package index when missing); its
        ``args_non_parallel``/``args_parallel`` become the task's kwargs. Filters
        are not present in this format and so cannot be restored.
        """
        steps: list[Task | Filter] = []
        for entry in data.get("task_list", []):
            task_ref = entry["task"]
            resolved = _resolve_task(
                task_ref["pkg_name"],
                task_ref.get("version"),
                task_ref["name"],
                registry,
            )
            steps.append(
                resolved.model_copy(
                    update={
                        "kwargs_non_parallel": entry.get("args_non_parallel"),
                        "kwargs_parallel": entry.get("args_parallel"),
                    }
                )
            )
        return cls(
            name=data.get("name", "Unnamed Workflow"),
            description=data.get("description"),
            task_list=steps,
        )

    @classmethod
    def from_fractal_json(cls, data: str, registry: TasksRegistry) -> "Workflow":
        """Reconstruct a workflow from a Fractal workflow-export JSON string."""
        return cls.from_fractal_dict(json.loads(data), registry)
