import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fractal_lite._dataset import Dataset

# A callback invoked once per line of subprocess output (newline stripped).
OnOutput = Callable[[str], None]


class RunCancelled(Exception):
    """Raised to unwind the run call chain when a task run is cancelled."""


class Cancellation:
    """Cooperative cancel token shared across the UI and worker threads.

    The UI thread calls :meth:`cancel`; each worker thread (running one task
    subprocess) calls :meth:`register` once it has spawned its subprocess and
    :meth:`unregister` once it finishes. A lock plus the "terminate on late
    register" guard handle the race where ``cancel`` fires after the event is
    checked but before (or while) a process is spawned. A *set* of processes is
    tracked so the parallel phase can run several subprocesses concurrently and
    have them all terminated on cancel.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        """Mark as cancelled and terminate every currently-running process."""
        self._event.set()
        with self._lock:
            for proc in self._procs:
                if proc.poll() is None:
                    proc.terminate()

    def register(self, proc: subprocess.Popen) -> None:
        """Track a live subprocess; terminate at once if already cancelled."""
        with self._lock:
            self._procs.add(proc)
            if self._event.is_set():
                proc.terminate()

    def unregister(self, proc: subprocess.Popen) -> None:
        """Stop tracking a subprocess once it has finished."""
        with self._lock:
            self._procs.discard(proc)


class RunMetrics:
    """Thread-safe collector for per-image (parallel-item) runtimes.

    The UI creates one per run and passes it down the run chain; the parallel
    runner records each item's *measured* wall-clock duration. The mean of these
    is reported alongside the total run time, and is deliberately distinct from
    ``total / n_images`` since concurrent items overlap in wall-clock time.
    """

    def __init__(self) -> None:
        self.item_durations: list[float] = []
        self._lock = threading.Lock()

    def record_item(self, seconds: float) -> None:
        """Record one parallel item's measured duration (in seconds)."""
        with self._lock:
            self.item_durations.append(seconds)

    @property
    def mean_item_seconds(self) -> float | None:
        """Average of measured per-item durations, or ``None`` if none ran."""
        with self._lock:
            if not self.item_durations:
                return None
            return sum(self.item_durations) / len(self.item_durations)


def _run_executable(
    kwargs: dict[str, Any],
    executable: str,
    source_location: Path,
    pyproject_path: Path,
    *,
    on_output: OnOutput | None = None,
    cancellation: Cancellation | None = None,
) -> dict[str, Any]:
    """Run a single Fractal task executable in its own pixi environment.

    Serializes ``kwargs`` to a temporary JSON file, invokes the executable
    through ``pixi run`` (so it uses the task package's own environment),
    streams its merged stdout/stderr line-by-line, and deserializes the JSON
    written by the task.

    Args:
        kwargs: Keyword arguments forwarded to the task function.
        executable: Path to the executable relative to ``source_location``.
        source_location: Directory containing the task manifest and scripts.
        pyproject_path: Path to the package's pixi manifest (pyproject.toml).
        on_output: Called once per output line; if ``None``, lines are printed.
        cancellation: Cooperative cancel token; when triggered the subprocess
            is terminated and :class:`RunCancelled` is raised.

    Returns:
        The dictionary deserialized from the task's output JSON file.

    Raises:
        RunCancelled: If the run was cancelled via ``cancellation``.
        RuntimeError: If the executable exits with a non-zero status.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        args_json = Path(tmp_dir) / "args.json"
        out_json = Path(tmp_dir) / "out.json"
        with open(args_json, "w") as f:
            json.dump(kwargs, f)

        cmd = [
            "pixi",
            "run",
            "--manifest-path",
            str(pyproject_path),
            "python",
            str(source_location / executable),
            "--args-json",
            str(args_json),
            "--out-json",
            str(out_json),
        ]
        # Merge stderr into stdout so the read loop preserves interleaving, and
        # force the child to flush per line so output streams live.
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        if cancellation is not None:
            cancellation.register(proc)

        output_lines: list[str] = []
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                output_lines.append(line)
                if on_output is not None:
                    on_output(line)
                else:
                    print(line)
            proc.wait()
        finally:
            if cancellation is not None:
                cancellation.unregister(proc)

        if cancellation is not None and cancellation.cancelled:
            raise RunCancelled
        if proc.returncode != 0:
            raise RuntimeError(
                f"Task executable {executable} failed with exit code "
                f"{proc.returncode}.\n--- output ---\n" + "\n".join(output_lines)
            )

        with open(out_json) as f:
            return json.load(f)


def _run_non_parallel_task(
    kwargs_non_parallel: dict[str, Any],
    executable_non_parallel: str,
    source_location: Path,
    pyproject_path: Path,
    *,
    on_output: OnOutput | None = None,
    cancellation: Cancellation | None = None,
) -> dict[str, Any]:
    """Run the non-parallel (init) phase of a task and return its output."""
    return _run_executable(
        kwargs_non_parallel,
        executable_non_parallel,
        source_location,
        pyproject_path,
        on_output=on_output,
        cancellation=cancellation,
    )


def _run_parallel_task(
    kwargs_parallel: list[dict[str, Any]],
    executable_parallel: str,
    source_location: Path,
    pyproject_path: Path,
    *,
    on_output: OnOutput | None = None,
    cancellation: Cancellation | None = None,
    max_workers: int = 1,
    metrics: RunMetrics | None = None,
) -> list[dict[str, Any] | None]:
    """Run the parallel phase once per item across a pool of subprocesses.

    Up to ``max_workers`` items run concurrently, each in its own ``pixi run``
    subprocess (the heavy work is already out-of-process, so a thread pool that
    blocks on subprocess I/O is the right tool). Output is preserved in input
    order. Each item's streamed lines are prefixed with ``[i/N]`` so concurrent
    streams stay readable.

    All items are attempted even if some fail; afterwards a single
    :class:`RuntimeError` aggregating the failures is raised (run-all-then-report).

    Returns the list of output dictionaries (or ``None`` for items that mutate
    in place), one per input item, in input order.

    Raises:
        RunCancelled: If the run was cancelled via ``cancellation``.
        RuntimeError: If one or more items failed.
    """
    n = len(kwargs_parallel)
    results: list[dict[str, Any] | None] = [None] * n
    errors: list[tuple[int, Exception]] = []
    # Serialize on_output calls so lines from concurrent items aren't interleaved
    # mid-line in the shared log.
    output_lock = threading.Lock()

    def run_one(index: int, kwargs: dict[str, Any]) -> dict[str, Any]:
        if cancellation is not None and cancellation.cancelled:
            raise RunCancelled
        item_on_output: OnOutput | None = None
        if on_output is not None:

            def item_on_output(line: str, _i: int = index) -> None:
                with output_lock:
                    on_output(f"[{_i + 1}/{n}] {line}")

        started = time.perf_counter()
        try:
            return _run_executable(
                kwargs,
                executable_parallel,
                source_location,
                pyproject_path,
                on_output=item_on_output,
                cancellation=cancellation,
            )
        finally:
            if metrics is not None:
                metrics.record_item(time.perf_counter() - started)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_to_index = {
            executor.submit(run_one, i, kwargs): i
            for i, kwargs in enumerate(kwargs_parallel)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except RunCancelled:
                # Cancellation unwinds the whole run; siblings were already
                # terminated by Cancellation.cancel().
                raise
            except Exception as exc:
                # Collected and reported after every item is attempted.
                errors.append((index, exc))

    if cancellation is not None and cancellation.cancelled:
        raise RunCancelled
    if errors:
        first_index, first_exc = errors[0]
        raise RuntimeError(
            f"{len(errors)}/{n} parallel items failed. "
            f"First error (item {first_index + 1}): {first_exc}"
        )
    return results


def _flatten_updates(
    results: list[dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """Collect the ``image_list_updates`` from per-item task results, in order.

    Results that are ``None`` or carry no updates (a task that mutates its zarr
    in place) contribute nothing.
    """
    updates: list[dict[str, Any]] = []
    for result in results:
        if result and result.get("image_list_updates"):
            updates.extend(result["image_list_updates"])
    return updates


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
        # Phase 1: non-parallel (init) produces the parallelization list.
        init_kwargs = {**(kwargs_non_parallel or {}), "zarr_dir": zarr_dir}
        init_out = _run_non_parallel_task(
            init_kwargs,
            self.executable_non_parallel,
            source_location,
            pyproject_path,
            on_output=on_output,
            cancellation=cancellation,
        )
        parallelization_list = init_out["parallelization_list"]

        # Phase 2: run the parallel executable once per item, concurrently.
        per_item_kwargs = [
            {**item, **(kwargs_parallel or {})} for item in parallelization_list
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
        return _flatten_updates(results)


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
        # Phase 1: init receives the selected ``run_urls``, not zarr_dir.
        init_kwargs = {
            **(kwargs_non_parallel or {}),
            "zarr_urls": run_urls,
            "zarr_dir": zarr_dir,
        }
        init_out = _run_non_parallel_task(
            init_kwargs,
            self.executable_non_parallel,
            source_location,
            pyproject_path,
            on_output=on_output,
            cancellation=cancellation,
        )
        parallelization_list = init_out["parallelization_list"]

        # Phase 2: run the parallel executable once per item, concurrently.
        per_item_kwargs = [
            {**item, **(kwargs_parallel or {})} for item in parallelization_list
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
        return _flatten_updates(results)


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
        for parent in [location, *location.parents]:
            candidate = parent / "pyproject.toml"
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"No pyproject.toml found above {location}.")

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

        # Input-types: run only on the non-hidden images that match (converters
        # consume ``zarr_dir`` instead, so they have no input images).
        if self.task.consumes_images:
            run_urls = [
                zu.url
                for zu in dataset.zarr_urls
                if not zu.hidden and zu.matches_input_types(self.task.input_types)
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
