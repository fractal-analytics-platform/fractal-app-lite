"""A ``Project``: the current application state, persisted as a directory of files.

A project directory holds one file per concern rather than a single bundle::

    <project_dir>/
        project.json            # the index (name, zarr_dir, max_workers, filenames)
        table.csv               # the dataset (written only when it has images)
        workflow.json           # the current workflow (task schemas blanked)
        sandbox_history.json    # the sandbox run-history
        workflow_history.json   # the workflow run-history
        registry.json           # the task-registry sources

:class:`Project` is the in-process state object (the replacement for the backend's
``AppState``): mutate ``project.dataset`` / ``.workflow`` / ``.sandbox_history`` /
``.workflow_history`` / ``.registry`` in place, then :meth:`save` (whole project) or one
of the ``save_*`` methods (a single artifact). The task registry is owned per-project
(``project.registry``), not a global singleton.

Filenames in :class:`ProjectIndex` are relative to the project directory, so the
directory can be moved freely and still load. Large, regenerable task ``args_schema_*``
are stripped before writing and rebuilt on load from the (re-collected) registry.
"""

import contextlib
import json
from pathlib import Path

from pydantic import BaseModel

from fractal_lite.__version__ import __version__ as _APP_VERSION
from fractal_lite._dataset import Dataset
from fractal_lite._history import SandboxHistory, WorkflowHistory
from fractal_lite._registry import TasksRegistry
from fractal_lite._workflow import Workflow, strip_task_schemas

# Name of the index file at the root of every project directory.
INDEX_FILENAME = "project.json"


class ProjectIndex(BaseModel):
    """The ``project.json`` index: project metadata + relative artifact filenames."""

    version: int = 1
    fractal_lite_version: str = _APP_VERSION
    name: str = "Project"
    description: str = ""
    # The dataset's ``zarr_dir`` (stored here so it round-trips faithfully; the CSV
    # can only infer it lossily).
    zarr_dir: str
    max_workers: int = 1
    # Filenames relative to the project directory.
    dataset_file: str = "table.csv"
    workflow_file: str = "workflow.json"
    sandbox_history_file: str = "sandbox_history.json"
    workflow_history_file: str = "workflow_history.json"
    registry_file: str = "registry.json"


class Project:
    """The current state of a sandbox session, backed by a project directory."""

    def __init__(
        self,
        project_dir: str | Path,
        index: ProjectIndex,
        dataset: Dataset,
        workflow: Workflow,
        sandbox_history: SandboxHistory,
        workflow_history: WorkflowHistory,
        registry: TasksRegistry,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.index = index
        self.dataset = dataset
        self.workflow = workflow
        self.sandbox_history = sandbox_history
        self.workflow_history = workflow_history
        self.registry = registry

    # --- Convenience read/write-through accessors onto the index -----------

    @property
    def name(self) -> str:
        return self.index.name

    @name.setter
    def name(self, value: str) -> None:
        self.index.name = value

    @property
    def description(self) -> str:
        return self.index.description

    @description.setter
    def description(self, value: str) -> None:
        self.index.description = value

    @property
    def max_workers(self) -> int:
        return self.index.max_workers

    @max_workers.setter
    def max_workers(self, value: int) -> None:
        self.index.max_workers = value

    @property
    def zarr_dir(self) -> str:
        return self.index.zarr_dir

    # --- Construction ------------------------------------------------------

    @classmethod
    def create(
        cls,
        project_dir: str | Path,
        *,
        name: str,
        zarr_dir: str,
        description: str = "",
        max_workers: int = 1,
        exist_ok: bool = False,
    ) -> "Project":
        """Create the project directory and an empty project, then persist it.

        The dataset and workflow are named after the project; the histories start
        empty. The project gets a fresh, empty task registry, whose (empty) sources
        are written too.
        """
        project_dir = Path(project_dir)
        project_dir.mkdir(parents=True, exist_ok=exist_ok)
        index = ProjectIndex(
            name=name,
            description=description,
            zarr_dir=zarr_dir,
            max_workers=max_workers,
        )
        project = cls(
            project_dir=project_dir,
            index=index,
            dataset=Dataset(name=name, zarr_dir=zarr_dir),
            workflow=Workflow(name=name),
            sandbox_history=SandboxHistory(),
            workflow_history=WorkflowHistory(),
            registry=TasksRegistry(),
        )
        project.save()
        return project

    @classmethod
    def load(cls, project_dir: str | Path) -> "Project":
        """Load a project from its directory, rebuilding regenerable data.

        The registry sources are loaded and re-collected first (best-effort) so the
        workflow's and workflow-history's task schemas can be re-resolved against it.
        """
        project_dir = Path(project_dir)
        index = ProjectIndex.model_validate_json(
            (project_dir / INDEX_FILENAME).read_text()
        )

        # Registry first: re-collecting it populates the schemas the workflow and
        # history snapshots reference. Best-effort — a moved/unavailable source must
        # not block restoring the rest of the project.
        registry = TasksRegistry()
        registry_path = project_dir / index.registry_file
        if registry_path.exists():
            with contextlib.suppress(Exception):
                registry.load_from_json(registry_path)

        dataset = cls._load_dataset(project_dir, index)

        workflow_path = project_dir / index.workflow_file
        if workflow_path.exists():
            workflow = Workflow.from_json(workflow_path.read_text()).resolve_schemas(
                registry
            )
        else:
            workflow = Workflow(name=index.name)

        sandbox_path = project_dir / index.sandbox_history_file
        sandbox_history = (
            SandboxHistory.from_json(sandbox_path.read_text())
            if sandbox_path.exists()
            else SandboxHistory()
        )

        workflow_history = cls._load_workflow_history(project_dir, index, registry)

        return cls(
            project_dir=project_dir,
            index=index,
            dataset=dataset,
            workflow=workflow,
            sandbox_history=sandbox_history,
            workflow_history=workflow_history,
            registry=registry,
        )

    @staticmethod
    def _load_dataset(project_dir: Path, index: ProjectIndex) -> Dataset:
        """Load the dataset from ``table.csv``, restoring its faithful name/zarr_dir.

        ``Dataset.from_csv`` infers ``name`` from the filename and ``zarr_dir`` from
        the common path of the URLs (both lossy), so the values stored in the index
        are reapplied. An absent/empty CSV yields an empty dataset.
        """
        path = project_dir / index.dataset_file
        if path.exists():
            with contextlib.suppress(ValueError):
                loaded = Dataset.from_csv(path)
                return Dataset(
                    name=index.name,
                    zarr_dir=index.zarr_dir,
                    zarr_urls=loaded.zarr_urls,
                )
        return Dataset(name=index.name, zarr_dir=index.zarr_dir)

    @staticmethod
    def _load_workflow_history(
        project_dir: Path, index: ProjectIndex, registry: TasksRegistry
    ) -> WorkflowHistory:
        path = project_dir / index.workflow_history_file
        if not path.exists():
            return WorkflowHistory()
        history = WorkflowHistory.from_json(path.read_text())
        for record in history.records:
            if record.workflow is not None:
                record.workflow = record.workflow.resolve_schemas(registry)
        return history

    # --- Persistence -------------------------------------------------------

    def save(self) -> None:
        """Write every artifact and the index to the project directory."""
        self.save_dataset()
        self.save_workflow()
        self.save_sandbox_history()
        self.save_workflow_history()
        self.save_registry()
        # Index last: ``save_dataset`` syncs name/zarr_dir onto it first.
        self.save_index()

    def save_index(self) -> None:
        (self.project_dir / INDEX_FILENAME).write_text(
            self.index.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def save_dataset(self) -> None:
        """Write the dataset to ``table.csv`` and sync its ``zarr_dir`` to the index.

        ``zarr_dir`` is dataset-driven, so it is mirrored onto the index (the CSV
        can only infer it lossily). The dataset's ``name`` is not persisted — the
        project ``name`` is authoritative and reapplied on load. An empty dataset
        writes no CSV (and removes a stale one), so it reloads as an empty dataset
        rather than tripping ``Dataset.from_csv``'s empty-file guard.
        """
        self.index.zarr_dir = self.dataset.zarr_dir
        path = self.project_dir / self.index.dataset_file
        if self.dataset.zarr_urls:
            self.dataset.to_csv(path)
        elif path.exists():
            path.unlink()

    def save_workflow(self) -> None:
        data = strip_task_schemas(self.workflow.model_dump(mode="json"))
        (self.project_dir / self.index.workflow_file).write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

    def save_sandbox_history(self) -> None:
        (self.project_dir / self.index.sandbox_history_file).write_text(
            self.sandbox_history.to_json()
        )

    def save_workflow_history(self) -> None:
        # Reuse History.to_json (summary truncation), then blank the regenerable
        # task schemas embedded in each record's workflow snapshot.
        data = strip_task_schemas(json.loads(self.workflow_history.to_json()))
        (self.project_dir / self.index.workflow_history_file).write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

    def save_registry(self) -> None:
        self.registry.dump_to_json(self.project_dir / self.index.registry_file)
