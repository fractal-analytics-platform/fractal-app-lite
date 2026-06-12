import json
from pathlib import Path

from pydantic import BaseModel, Field

from fractal_lite._collect import (
    _fractal_collection_dir,
    _recompute_version,
    collect_from_dir,
    collect_from_gitrelease,
    collect_from_source_info,
    collect_from_targz,
)
from fractal_lite._tasks import Task, TaskSourceInfo
from fractal_lite._write_text import write_dict_to_file


class TasksRegistryModel(BaseModel):
    packages: dict[str, Task] = Field(default_factory=dict)
    sources: set[TaskSourceInfo] = Field(default_factory=set)
    collection_dir: Path = Field(default_factory=_fractal_collection_dir)


class TasksRegistry:
    def __init__(self, registry: TasksRegistryModel | None = None) -> None:
        self._registry = registry if registry is not None else TasksRegistryModel()

    @property
    def tasks(self) -> list[Task]:
        return list(self._registry.packages.values())

    def get_task(self, name: str) -> Task:
        try:
            return self._registry.packages[name]
        except KeyError:
            raise KeyError(
                f"Task {name!r} not found. Available: {sorted(self._registry.packages)}"
            ) from None

    def recollect_tasks(self) -> None:
        """Re-collect every registered task from its stored source.

        Rebuilds each package from its source (refreshing ``source_location`` by
        re-extracting/parsing it). Sources that cannot be recollected (e.g. a
        moved directory or unreachable release) propagate their error.
        """
        for source_info in list(self._registry.sources):
            tasks = collect_from_source_info(source_info, self._registry.collection_dir)
            self._add_all(tasks, overwrite=True)

    def add_task(self, task: Task, overwrite: bool = False) -> None:
        """Register a single, already-collected task (e.g. from a loaded workflow)."""
        self._add_task(task, overwrite=overwrite)

    def _add_task(self, task: Task, overwrite: bool = False) -> None:
        if not overwrite and task.unique_id in self._registry.packages:
            raise ValueError(f"Task with id {task.unique_id} already exists.")
        # The registry holds task templates only; arguments are supplied by the
        # consumer (run/workflow), never stored here.
        task = task.model_copy(
            update={"kwargs_non_parallel": None, "kwargs_parallel": None}
        )
        self._registry.packages[task.unique_id] = task
        self._registry.sources.add(task.source_info)

    def _add_all(self, tasks: list[Task], overwrite: bool) -> None:
        for task in tasks:
            self._add_task(task, overwrite=overwrite)

    def collect_from_directory(self, task_path: Path, overwrite: bool = False) -> None:
        """Collect tasks from a local directory.

        Directory must contain a pixi-installable fractal
        task package
        """
        tasks = collect_from_dir(
            task_path=task_path, collection_dir=self._registry.collection_dir
        )
        self._add_all(tasks, overwrite)

    def collect_from_targz(self, task_path: Path, overwrite: bool = False) -> None:
        """Collect tasks from a tar.gz archive.

        Archive must contain a pixi-installable fractal
        task package
        """
        tasks = collect_from_targz(
            task_path=task_path, collection_dir=self._registry.collection_dir
        )
        self._add_all(tasks, overwrite)

    def collect_from_gitrelease(
        self, repo_url: str, tag: str | None = None, overwrite: bool = False
    ) -> None:
        """Collect tasks from a Git release.

        The repository must contain a pixi-installable fractal
        task package part of the Git release.
        """
        tasks = collect_from_gitrelease(
            repo_url=repo_url, tag=tag, collection_dir=self._registry.collection_dir
        )
        self._add_all(tasks, overwrite)

    def dump_to_json(self, path: str | Path) -> None:
        """Dump the registry's sources to a JSON file.

        Packages are not persisted: they are fully rebuilt from the sources on
        load (see :meth:`load_from_json`).
        """
        write_dict_to_file(path, self.to_sources_dict())

    def load_from_json(self, path: str | Path) -> None:
        """Load a registry file and rebuild its packages from the stored sources.

        Self-contained: re-collects every source. Backward-compatible with older
        full-package dumps — any inline ``packages``/``package_kwargs`` are ignored
        and the packages are rebuilt from the sources.
        """
        self.load_from_dict(json.loads(Path(path).read_text()))
        self.recollect_tasks()

    def to_sources_dict(self) -> dict:
        """Return only the registry's ``sources`` (+ ``collection_dir``).

        The ``packages`` are omitted: they (and their large embedded JSON schemas)
        are fully reconstructable from the sources via :meth:`recollect_tasks`, so
        leaving them out keeps an embedded/saved registry small.
        """
        return self._registry.model_dump(mode="json", exclude={"packages"})

    def load_from_dict(self, data: dict) -> None:
        """Replace the registry from a dict produced by :meth:`to_sources_dict`."""
        self._registry = TasksRegistryModel.model_validate(data)
        self._refresh_versions()

    def _refresh_versions(self) -> None:
        """Re-derive every stored source's version after a load.

        The version baked into a dump can go stale (most importantly for a
        locally-installed package that was upgraded), so it is recomputed from
        the live source on every load instead of being trusted from the JSON.
        Equal sources share a single computation to avoid repeated pixi calls.
        """
        cache: dict[TaskSourceInfo, str | None] = {}

        def version_for(source_info: TaskSourceInfo) -> str | None:
            key = source_info.model_copy(update={"version": None})
            if key not in cache:
                cache[key] = _recompute_version(source_info)
            return cache[key]

        for unique_id, task in list(self._registry.packages.items()):
            version = version_for(task.source_info)
            if version != task.source_info.version:
                source_info = task.source_info.model_copy(update={"version": version})
                self._registry.packages[unique_id] = task.model_copy(
                    update={"source_info": source_info}
                )
        self._registry.sources = {
            s.model_copy(update={"version": version_for(s)})
            for s in self._registry.sources
        }
