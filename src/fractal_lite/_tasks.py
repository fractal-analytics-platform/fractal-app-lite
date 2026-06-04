from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fractal_lite._dataset import Dataset
from fractal_lite._execution import (
    Cancellation,
    OnOutput,
    RunMetrics,
    _flatten_updates,
    _run_non_parallel_task,
    _run_parallel_task,
)


def _find_pyproject(start: Path) -> Path | None:
    """Return the nearest ``pyproject.toml`` at or above ``start``, if any."""
    for parent in [start, *start.parents]:
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _run_compound(
    init_kwargs: dict[str, Any],
    executable_non_parallel: str,
    executable_parallel: str,
    kwargs_parallel: dict[str, Any] | None,
    source_location: Path,
    pyproject_path: Path,
    *,
    on_output: OnOutput | None = None,
    cancellation: Cancellation | None = None,
    max_workers: int = 1,
    metrics: RunMetrics | None = None,
) -> list[dict[str, Any]]:
    """Run a compound task: a non-parallel init phase then a parallel phase.

    Shared by the compound task types, which differ only in the ``init_kwargs``
    they build. Phase 1 (init) produces a ``parallelization_list``; phase 2 runs
    the parallel executable once per item (concurrently), overlaying
    ``kwargs_parallel`` onto each item.
    """
    init_out = _run_non_parallel_task(
        init_kwargs,
        executable_non_parallel,
        source_location,
        pyproject_path,
        on_output=on_output,
        cancellation=cancellation,
    )
    per_item_kwargs = [
        {**item, **(kwargs_parallel or {})} for item in init_out["parallelization_list"]
    ]
    results = _run_parallel_task(
        per_item_kwargs,
        executable_parallel,
        source_location,
        pyproject_path,
        on_output=on_output,
        cancellation=cancellation,
        max_workers=max_workers,
        metrics=metrics,
    )
    return _flatten_updates(results)


class TaskTypeBase(BaseModel):
    name: str
    category: str | None = None
    modality: str | None = None
    tags: list[str] = Field(default_factory=list)
    docs_info: str | None = None
    docs_link: str | None = None
    input_types: dict[str, bool] = Field(default_factory=dict)
    output_types: dict[str, bool] = Field(default_factory=dict)

    @property
    def consumes_images(self) -> bool:
        """Whether the task runs on the dataset's images (vs. ``zarr_dir``).

        Converters read from ``zarr_dir`` and create images from scratch, so
        they have no input images for ``input_types``/``output_types`` to act on.
        """
        return True


class ConverterCompoundTask(TaskTypeBase):
    type: Literal["converter_compound"]
    # Parallel
    executable_parallel: str
    args_schema_parallel: dict[str, Any]
    meta_parallel: dict[str, Any] = Field(default_factory=dict)
    # Non parallel
    executable_non_parallel: str
    args_schema_non_parallel: dict[str, Any]
    meta_non_parallel: dict[str, Any] = Field(default_factory=dict)

    @property
    def consumes_images(self) -> bool:
        return False

    def execute(
        self,
        zarr_dir: str,
        run_urls: list[str],
        kwargs_non_parallel: dict[str, Any] | None,
        kwargs_parallel: dict[str, Any] | None,
        source_location: Path,
        pyproject_path: Path,
        *,
        on_output: OnOutput | None = None,
        cancellation: Cancellation | None = None,
        max_workers: int = 1,
        metrics: RunMetrics | None = None,
    ) -> list[dict[str, Any]]:
        # Converter: init reads ``zarr_dir`` and ignores ``run_urls``.
        init_kwargs = {**(kwargs_non_parallel or {}), "zarr_dir": zarr_dir}
        return _run_compound(
            init_kwargs,
            self.executable_non_parallel,
            self.executable_parallel,
            kwargs_parallel,
            source_location,
            pyproject_path,
            on_output=on_output,
            cancellation=cancellation,
            max_workers=max_workers,
            metrics=metrics,
        )


class CompoundTask(TaskTypeBase):
    type: Literal["compound"]
    # Parallel
    executable_parallel: str
    args_schema_parallel: dict[str, Any]
    meta_parallel: dict[str, Any] = Field(default_factory=dict)
    # Non parallel (init)
    executable_non_parallel: str
    args_schema_non_parallel: dict[str, Any]
    meta_non_parallel: dict[str, Any] = Field(default_factory=dict)

    def execute(
        self,
        zarr_dir: str,
        run_urls: list[str],
        kwargs_non_parallel: dict[str, Any] | None,
        kwargs_parallel: dict[str, Any] | None,
        source_location: Path,
        pyproject_path: Path,
        *,
        on_output: OnOutput | None = None,
        cancellation: Cancellation | None = None,
        max_workers: int = 1,
        metrics: RunMetrics | None = None,
    ) -> list[dict[str, Any]]:
        # Init receives the selected ``run_urls`` (and zarr_dir), not just zarr_dir.
        init_kwargs = {
            **(kwargs_non_parallel or {}),
            "zarr_urls": run_urls,
            "zarr_dir": zarr_dir,
        }
        return _run_compound(
            init_kwargs,
            self.executable_non_parallel,
            self.executable_parallel,
            kwargs_parallel,
            source_location,
            pyproject_path,
            on_output=on_output,
            cancellation=cancellation,
            max_workers=max_workers,
            metrics=metrics,
        )


class ConverterNonParallelTask(TaskTypeBase):
    type: Literal["converter_non_parallel"]
    # Non parallel
    executable_non_parallel: str
    args_schema_non_parallel: dict[str, Any]
    meta_non_parallel: dict[str, Any] = Field(default_factory=dict)

    @property
    def consumes_images(self) -> bool:
        return False

    def execute(
        self,
        zarr_dir: str,
        run_urls: list[str],
        kwargs_non_parallel: dict[str, Any] | None,
        kwargs_parallel: dict[str, Any] | None,
        source_location: Path,
        pyproject_path: Path,
        *,
        on_output: OnOutput | None = None,
        cancellation: Cancellation | None = None,
        max_workers: int = 1,  # no parallel phase; accepted for a uniform signature
        metrics: RunMetrics | None = None,  # unused: no per-image phase to measure
    ) -> list[dict[str, Any]]:
        # Converter: reads ``zarr_dir`` and ignores ``run_urls``.
        kwargs = {**(kwargs_non_parallel or {}), "zarr_dir": zarr_dir}
        result = _run_non_parallel_task(
            kwargs,
            self.executable_non_parallel,
            source_location,
            pyproject_path,
            on_output=on_output,
            cancellation=cancellation,
        )
        return _flatten_updates([result])


class ParallelTask(TaskTypeBase):
    type: Literal["parallel"]
    # Parallel
    executable_parallel: str
    args_schema_parallel: dict[str, Any]
    meta_parallel: dict[str, Any] = Field(default_factory=dict)

    def execute(
        self,
        zarr_dir: str,
        run_urls: list[str],
        kwargs_non_parallel: dict[str, Any] | None,
        kwargs_parallel: dict[str, Any] | None,
        source_location: Path,
        pyproject_path: Path,
        *,
        on_output: OnOutput | None = None,
        cancellation: Cancellation | None = None,
        max_workers: int = 1,
        metrics: RunMetrics | None = None,
    ) -> list[dict[str, Any]]:
        # One parallel invocation per selected ``run_url``.
        per_item_kwargs = [
            {"zarr_url": url, **(kwargs_parallel or {})} for url in run_urls
        ]
        results = _run_parallel_task(
            per_item_kwargs,
            self.executable_parallel,
            source_location,
            pyproject_path,
            on_output=on_output,
            cancellation=cancellation,
            max_workers=max_workers,
            metrics=metrics,
        )
        # A task that returns None mutates the zarr in place and reports no
        # updates; ``_flatten_updates`` drops those.
        return _flatten_updates(results)


TaskType = Annotated[
    ConverterCompoundTask | CompoundTask | ConverterNonParallelTask | ParallelTask,
    Field(discriminator="type"),
]


class DirectoryTaskSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["Directory"] = "Directory"
    path: Path
    source_location: Path
    # ``package_id`` is the local-origin identifier (``local:<stem>``);
    # ``pkg_name`` is the distribution name from pyproject (``[project].name``),
    # which matches the curated package index and Fractal's ``task.pkg_name``.
    package_id: str
    pkg_name: str | None = None
    version: str | None = None

    @property
    def reference(self) -> str:
        """Human-readable origin of the package (the local directory path)."""
        return str(self.path)


class GitReleaseTaskSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["GitRelease"] = "GitRelease"
    repo_url: str
    tag: str
    source_location: Path
    # ``package_id`` is the git-origin identifier (``<repo>@<tag>``);
    # ``pkg_name`` is the distribution name from pyproject (``[project].name``).
    package_id: str
    pkg_name: str | None = None
    version: str | None = None

    @property
    def reference(self) -> str:
        """Human-readable origin of the package (the GitHub repository URL)."""
        return self.repo_url


class TarballTaskSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["Tarball"] = "Tarball"
    path: Path
    source_location: Path
    # ``package_id`` is the tarball-origin identifier; ``pkg_name`` is the
    # distribution name from pyproject (``[project].name``).
    package_id: str
    pkg_name: str | None = None
    version: str | None = None

    @property
    def reference(self) -> str:
        """Human-readable origin of the package (the local tarball path)."""
        return str(self.path)


TaskSourceInfo = Annotated[
    DirectoryTaskSource | GitReleaseTaskSource | TarballTaskSource,
    Field(discriminator="type"),
]


class Task(BaseModel):
    task: TaskType
    source_info: TaskSourceInfo
    kwargs_non_parallel: dict[str, Any] | None = None
    kwargs_parallel: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return self.task.name

    @property
    def category(self) -> str | None:
        return self.task.category

    @property
    def modality(self) -> str | None:
        return self.task.modality

    @property
    def tags(self) -> list[str]:
        return self.task.tags

    @property
    def package_id(self) -> str:
        """Origin identifier of the package (``local:<stem>`` / ``<repo>@<tag>``)."""
        return self.source_info.package_id

    @property
    def pkg_name(self) -> str | None:
        """Distribution name (``[project].name``), matching Fractal's ``pkg_name``."""
        return self.source_info.pkg_name

    @property
    def version(self) -> str | None:
        """Normalized package version (``X.X.X``), or None if unknown."""
        return self.source_info.version

    @property
    def source(self) -> str:
        """Human-readable origin of the package (path or repo URL)."""
        return self.source_info.reference

    @property
    def unique_id(self) -> str:
        return f"{self.name} [{self.package_id}]"

    @property
    def pyproject_path(self) -> Path:
        # The pixi manifest lives at the package root, which is an ancestor of
        # the manifest directory (e.g. src/<pkg>/ for src-layout packages).
        location = self.source_info.source_location
        pyproject = _find_pyproject(location)
        if pyproject is None:
            raise FileNotFoundError(f"No pyproject.toml found above {location}.")
        return pyproject

    def run(
        self,
        dataset: Dataset,
        kwargs_non_parallel: dict[str, Any] | None = None,
        kwargs_parallel: dict[str, Any] | None = None,
        *,
        on_output: OnOutput | None = None,
        cancellation: Cancellation | None = None,
        max_workers: int = 1,
        metrics: RunMetrics | None = None,
    ) -> Dataset:
        """Run the task on ``dataset``, enforcing its input- and output-types.

        This is the single entry point for running a task — used both in
        isolation and as a workflow step — so the behaviour is identical either
        way. ``input_types`` transiently select which images are processed (a
        missing type key counts as a match); the task's ``image_list_updates``
        are folded in; then ``output_types`` are applied (see
        :meth:`Dataset.with_output_types`).
        """
        kwnp = (
            kwargs_non_parallel
            if kwargs_non_parallel is not None
            else self.kwargs_non_parallel
        )
        kwp = kwargs_parallel if kwargs_parallel is not None else self.kwargs_parallel

        # Input-types: run only on the active images that match (converters
        # consume ``zarr_dir`` instead, so they have no input images).
        if self.task.consumes_images:
            run_urls = [
                zu.url
                for zu in dataset.zarr_urls
                if zu.active and zu.matches_input_types(self.task.input_types)
            ]
        else:
            run_urls = []

        updates = self.task.execute(
            dataset.zarr_dir,
            run_urls,
            kwnp,
            kwp,
            self.source_info.source_location,
            self.pyproject_path,
            on_output=on_output,
            cancellation=cancellation,
            max_workers=max_workers,
            metrics=metrics,
        )

        folded = dataset.from_imagelist_update(updates)
        produced = [u["zarr_url"] for u in updates]
        return folded.with_output_types(run_urls, produced, self.task.output_types)
