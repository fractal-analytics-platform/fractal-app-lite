import json
import logging
import os
import re
import subprocess
import tarfile
import tomllib
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from fractal_lite._tasks import (
    DirectoryTaskSource,
    GitReleaseTaskSource,
    TarballTaskSource,
    Task,
    TaskSourceInfo,
)

logger = logging.getLogger(__name__)


def _fractal_collection_dir() -> Path:
    """Determine the directory where collected tasks are stored.

    Default is "./collected", but can be overridden by setting the
    FRACTAL_COLLECTION_DIR environment variable to a different path.
    """
    return Path(os.environ.get("FRACTAL_COLLECTION_DIR", "./collected"))


FRACTAL_COLLECTION_DIR = Path(os.environ.get("FRACTAL_COLLECTION_DIR", "./collected"))

# Fractal manifest task types this runner can model and execute. Each entry
# maps to a concrete class in ``_tasks.py``; anything else is skipped during
# collection.
SUPPORTED_TASK_TYPES = (
    "converter_compound",
    "compound",
    "converter_non_parallel",
    "parallel",
)


def _ensure_pixi_env(package_dir: Path) -> None:
    """Best-effort: install the package's pixi env if it isn't present yet.

    Tasks run via ``pixi run --manifest-path <pyproject>``, which needs an
    installed environment. Some task packages ship a ``.pixi`` directory
    already; for those that don't, try ``pixi install``. Failures (e.g. pixi
    not installed, no pixi config) are non-fatal for collection.
    """
    pyproject = package_dir / "pyproject.toml"
    if not pyproject.is_file() or (package_dir / ".pixi").is_dir():
        return
    if "[tool.pixi" not in pyproject.read_text():
        return
    try:
        subprocess.run(
            ["pixi", "install", "--manifest-path", str(pyproject)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning("Could not install pixi env for %s: %s", package_dir, e)


def _normalize_version(raw: str | None) -> str | None:
    """Normalize a version string to its dotted-number core (``X.X.X``).

    Strips surrounding whitespace and a leading ``v``/``V`` (so ``v0.5.2`` and
    ``0.5.2`` both become ``0.5.2``). Returns ``None`` when no dotted version
    can be found.
    """
    if not raw:
        return None
    raw = raw.strip()
    match = re.fullmatch(r"[vV]?(\d+(?:\.\d+)*)", raw)
    if match is None:
        # Fall back to the first dotted-number run inside a longer string.
        match = re.search(r"(\d+(?:\.\d+)+)", raw)
    return match.group(1) if match else None


def _version_from_artifact_name(name: str) -> str | None:
    """Extract a normalized version from an sdist/tarball name.

    ``fractal_lif_converters-0.6.0.tar.gz`` -> ``0.6.0`` (the trailing
    ``-<version>`` segment). Returns ``None`` when no version segment is found.
    """
    stem = name.removesuffix(".tar.gz").removesuffix(".tgz")
    match = re.search(r"-(\d+(?:\.\d+)+[0-9A-Za-z.\-+]*)$", stem)
    return _normalize_version(match.group(1)) if match else None


def _find_pyproject(start: Path) -> Path | None:
    """Return the nearest ``pyproject.toml`` at or above ``start``, if any."""
    for parent in [start, *start.parents]:
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _dist_name_from_pyproject(start: Path) -> str | None:
    """Read ``[project].name`` (the distribution name) from the nearest pyproject.

    This is the package's PyPI/distribution name (e.g. ``fractal-tasks-core``),
    which matches the curated package index and Fractal's ``task.pkg_name``.
    Any failure (no pyproject, malformed, missing key) yields ``None``.
    """
    pyproject = _find_pyproject(start)
    if pyproject is None:
        return None
    try:
        meta = tomllib.loads(pyproject.read_text())
        return meta["project"]["name"]
    except (KeyError, OSError, tomllib.TOMLDecodeError):
        return None


def _version_from_pixi_env(start: Path) -> str | None:
    """Best-effort: read the installed package version from its pixi env.

    Locates the ancestor ``pyproject.toml``, reads ``[project].name``, then asks
    the package's pixi environment for the installed distribution version (which
    handles dynamic versions, e.g. hatch-vcs). Any failure (no pyproject, pixi
    not installed, package not installed) yields ``None``.
    """
    pyproject = _find_pyproject(start)
    if pyproject is None:
        return None
    dist_name = _dist_name_from_pyproject(start)
    if dist_name is None:
        return None
    try:
        result = subprocess.run(
            [
                "pixi",
                "run",
                "--manifest-path",
                str(pyproject),
                "python",
                "-c",
                "import importlib.metadata as m,sys; print(m.version(sys.argv[1]))",
                dist_name,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        logger.warning("Could not determine version from pixi env for %s: %s", start, e)
        return None
    return _normalize_version(result.stdout)


def _recompute_version(source_info: TaskSourceInfo) -> str | None:
    """Re-derive a source's version from its live origin (no re-download).

    Mirrors how :func:`collect_from_gitrelease` / :func:`collect_from_targz` /
    :func:`collect_from_dir` originally compute the version, so a stored source
    can be refreshed cheaply (e.g. on registry load) without re-collecting:

    - GitRelease: from the tag.
    - Tarball, and a Directory whose ``path`` is a ``.tar.gz``
      (tarball-collected): from the artifact filename.
    - Directory (a real local directory): from the installed pixi env.
    """
    if isinstance(source_info, GitReleaseTaskSource):
        return _normalize_version(source_info.tag)
    if isinstance(source_info, TarballTaskSource):
        return _version_from_artifact_name(source_info.path.name)
    name = source_info.path.name
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return _version_from_artifact_name(name)
    return _version_from_pixi_env(source_info.source_location)


def find_manifest_file(
    package_dir: Path, manifest_name: str = "__FRACTAL_MANIFEST__.json"
) -> Path:
    manifest_path = list(package_dir.rglob(manifest_name))
    if len(manifest_path) == 0:
        raise FileNotFoundError(
            f"Manifest file {manifest_name} not found in the package."
        )
    elif len(manifest_path) > 1:
        raise FileExistsError(
            f"Multiple manifest files {manifest_name} found in the package."
        )
    return manifest_path[0]


def _extract_and_collect(
    tarball_path: Path, collection_dir: Path, source_info: TaskSourceInfo
) -> list[Task]:
    """Extract a ``.tar.gz`` task package into ``collection_dir`` and collect it.

    The package directory is the tarball's name with the ``.tar.gz`` suffix
    removed; ``source_info`` is forwarded to :func:`collect_from_dir` (whose
    ``source_location`` is then refined to the manifest's parent directory).
    """
    with tarfile.open(tarball_path, "r:gz") as tar:
        tar.extractall(path=collection_dir)
    package_dir = (
        collection_dir / tarball_path.name.removesuffix(".tar.gz")
    ).absolute()
    source_info = source_info.model_copy(update={"source_location": package_dir})
    return collect_from_dir(package_dir, collection_dir, source_info=source_info)


def collect_from_targz(task_path: Path, collection_dir: Path) -> list[Task]:
    task_info = DirectoryTaskSource(
        path=task_path.absolute(),
        source_location=collection_dir,
        package_id=task_path.name,
        version=_version_from_artifact_name(task_path.name),
    )
    return _extract_and_collect(task_path, collection_dir, source_info=task_info)


def collect_from_dir(
    task_path: Path, collection_dir: Path, source_info: TaskSourceInfo | None = None
) -> list[Task]:
    manifest_path = find_manifest_file(task_path)
    with open(manifest_path) as f:
        manifest = json.load(f)
    assert manifest["manifest_version"] == "2"
    # Executable paths in the manifest are relative to the manifest's directory.
    # The manifest's parent is the one place the extracted package dir is known
    # for every collection path, so resolve the distribution ``pkg_name`` here.
    pkg_name = _dist_name_from_pyproject(manifest_path.parent)
    if source_info is None:
        source_info = DirectoryTaskSource(
            path=task_path.absolute(),
            source_location=manifest_path.parent,
            package_id=f"local:{task_path.stem}",
            pkg_name=pkg_name,
            version=_version_from_pixi_env(manifest_path.parent),
        )
    else:
        source_info = source_info.model_copy(
            update={"source_location": manifest_path.parent, "pkg_name": pkg_name}
        )
    tasks = []
    for raw_task in manifest["task_list"]:
        if raw_task["type"] in SUPPORTED_TASK_TYPES:
            try:
                task = Task(task=raw_task, source_info=source_info)
                tasks.append(task)
            except Exception as e:
                logger.error(
                    "Error parsing task %r (executable %r): %s",
                    raw_task.get("name", "unknown"),
                    raw_task.get("executable_non_parallel", "unknown"),
                    e,
                )
                continue
        else:
            # Manifest task whose Fractal type the runner cannot execute yet.
            # See SUPPORTED_TASK_TYPES above for the full list of supported types.
            # Warn rather than drop silently so the gap is visible at collection time.
            logger.warning(
                "Skipping task %r: task type %r is not supported "
                "(see SUPPORTED_TASK_TYPES).",
                raw_task.get("name", "unknown"),
                raw_task["type"],
            )
    return tasks


def _parse_github_repo(repo_url: str) -> tuple[str, str]:
    """Extract ``(owner, repo)`` from a GitHub repository URL.

    Tolerates a trailing slash, a ``.git`` suffix, and full asset/release URLs
    (e.g. ``.../owner/repo/releases/download/...``) by taking the first two path
    segments.
    """
    parts = urlsplit(repo_url)
    if parts.netloc not in ("github.com", "www.github.com"):
        raise ValueError(f"Not a GitHub repository URL: {repo_url!r}")
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        raise ValueError(f"Could not parse owner/repo from URL: {repo_url!r}")
    owner, repo = segments[0], segments[1]
    return owner, repo.removesuffix(".git")


def _resolve_release_asset(
    owner: str, repo: str, tag: str | None
) -> tuple[str, str, str]:
    """Resolve a GitHub release's ``.tar.gz`` asset via the REST API.

    Queries the release for ``tag`` (or the latest release when ``tag`` is
    ``None``) and returns ``(download_url, asset_name, resolved_tag)`` for the
    first asset whose name ends in ``.tar.gz``.

    Raises:
        RuntimeError: If the release has no ``.tar.gz`` asset.
    """
    if tag is None:
        api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    else:
        api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(
        api_url, headers={"Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req) as resp:  # trusted GitHub API URL
        release = json.load(resp)
    resolved_tag = release["tag_name"]
    for asset in release.get("assets", []):
        if asset["name"].endswith(".tar.gz"):
            return asset["browser_download_url"], asset["name"], resolved_tag
    raise RuntimeError(
        f"No .tar.gz asset found in release {resolved_tag!r} of {owner}/{repo}."
    )


def collect_from_gitrelease(
    repo_url: str, tag: str | None, collection_dir: Path
) -> list[Task]:
    """Download a GitHub release tarball and collect the tasks it contains.

    The release's ``.tar.gz`` asset is resolved via the GitHub API (``tag=None``
    means the latest release), downloaded into ``collection_dir``, extracted, and
    collected. The resulting tasks carry a :class:`GitReleaseTaskSource` recording
    the concrete resolved tag, so they can be re-downloaded on recollection.
    """
    owner, repo = _parse_github_repo(repo_url)
    asset_url, asset_name, resolved_tag = _resolve_release_asset(owner, repo, tag)
    collection_dir.mkdir(parents=True, exist_ok=True)
    download_path = collection_dir / asset_name
    urllib.request.urlretrieve(asset_url, download_path)  # trusted GitHub asset URL
    source_info = GitReleaseTaskSource(
        repo_url=repo_url,
        tag=resolved_tag,
        source_location=collection_dir,
        package_id=f"{repo}@{resolved_tag}",
        version=_normalize_version(resolved_tag),
    )
    return _extract_and_collect(download_path, collection_dir, source_info=source_info)


def collect_from_source_info(
    source_info: TaskSourceInfo, collection_dir: Path
) -> list[Task]:
    if isinstance(source_info, DirectoryTaskSource):
        # Forward the stored source so re-collection preserves the package's
        # identity (``package_id``/``unique_id``). Tarball packages are stored as a
        # ``DirectoryTaskSource`` pointing at their extracted dir, so without this
        # they would be re-collected under a fresh ``local:`` id — changing their
        # unique_id and breaking kwargs preservation and workflow re-resolution.
        return collect_from_dir(
            source_info.source_location, collection_dir, source_info=source_info
        )
    elif isinstance(source_info, TarballTaskSource):
        return collect_from_targz(source_info.source_location, collection_dir)
    elif isinstance(source_info, GitReleaseTaskSource):
        return collect_from_gitrelease(
            source_info.repo_url, source_info.tag, collection_dir
        )
    else:
        raise ValueError(f"Unknown TaskSourceInfo type: {source_info}")


class TasksRegistryModel(BaseModel):
    packages: dict[str, Task] = Field(default_factory=dict)
    sources: set[TaskSourceInfo] = Field(default_factory=set)
    collection_dir: Path = Field(default_factory=_fractal_collection_dir)


# Singleton
class TasksRegistry:
    _instance = None
    _registry: TasksRegistryModel = TasksRegistryModel()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tasks = {}
        return cls._instance

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

        Refreshes each task's ``source_location`` by re-extracting/parsing its
        source, while preserving any per-task kwargs already configured. Sources
        that cannot be recollected (e.g. unimplemented git-release collection)
        propagate their error.
        """
        for source_info in list(self._registry.sources):
            tasks = collect_from_source_info(source_info, self._registry.collection_dir)
            for task in tasks:
                existing = self._registry.packages.get(task.unique_id)
                if existing is not None:
                    task = task.model_copy(
                        update={
                            "kwargs_non_parallel": existing.kwargs_non_parallel,
                            "kwargs_parallel": existing.kwargs_parallel,
                        }
                    )
                self._add_task(task, overwrite=True)

    def add_task(self, task: Task, overwrite: bool = False) -> None:
        """Register a single, already-collected task (e.g. from a loaded workflow)."""
        self._add_task(task, overwrite=overwrite)

    def _add_task(self, task: Task, overwrite: bool = False) -> None:
        if not overwrite and task.unique_id in self._registry.packages:
            raise ValueError(f"Task with id {task.unique_id} already exists.")
        self._registry.packages[task.unique_id] = task
        self._registry.sources.add(task.source_info)

    def collect_from_directory(self, task_path: Path, overwrite: bool = False) -> None:
        tasks = collect_from_dir(
            task_path=task_path, collection_dir=self._registry.collection_dir
        )
        for task in tasks:
            self._add_task(task, overwrite=overwrite)

    def collect_from_targz(self, task_path: Path, overwrite: bool = False) -> None:
        tasks = collect_from_targz(
            task_path=task_path, collection_dir=self._registry.collection_dir
        )
        for task in tasks:
            self._add_task(task, overwrite=overwrite)

    def collect_from_gitrelease(
        self, repo_url: str, tag: str | None = None, overwrite: bool = False
    ) -> None:
        tasks = collect_from_gitrelease(
            repo_url=repo_url, tag=tag, collection_dir=self._registry.collection_dir
        )
        for task in tasks:
            self._add_task(task, overwrite=overwrite)

    def dump_to_json(self, path: str | Path) -> None:
        Path(path).write_text(self._registry.model_dump_json(indent=2))

    def load_from_json(self, path: str | Path) -> None:
        self._registry = TasksRegistryModel.model_validate_json(Path(path).read_text())
        self._refresh_versions()

    def to_dict(self) -> dict:
        """Return the registry as a JSON-serializable dict (for embedding)."""
        return self._registry.model_dump(mode="json")

    def to_sources_dict(self) -> dict:
        """Return only the registry's ``sources`` (+ ``collection_dir``).

        The ``packages`` are omitted: they (and their large embedded JSON schemas)
        are fully reconstructable from the sources via :meth:`recollect_tasks`, so
        leaving them out keeps an embedded/saved registry small. Pair with
        :meth:`package_kwargs` to preserve any per-package kwargs that a bare
        re-collection would otherwise drop.
        """
        return self._registry.model_dump(mode="json", exclude={"packages"})

    def package_kwargs(self) -> dict[str, dict]:
        """Map ``unique_id -> {kwargs_non_parallel, kwargs_parallel}`` for packages.

        Only packages with at least one non-null kwargs entry are included, so a
        sources-only dump can re-apply them after re-collection (which preserves
        kwargs only from *existing* packages — absent after a sources-only load).
        """
        result: dict[str, dict] = {}
        for unique_id, task in self._registry.packages.items():
            if task.kwargs_non_parallel is None and task.kwargs_parallel is None:
                continue
            result[unique_id] = {
                "kwargs_non_parallel": task.kwargs_non_parallel,
                "kwargs_parallel": task.kwargs_parallel,
            }
        return result

    def apply_package_kwargs(self, kwargs_map: dict[str, dict]) -> None:
        """Overlay kwargs from :meth:`package_kwargs` onto current packages."""
        for unique_id, kwargs in (kwargs_map or {}).items():
            task = self._registry.packages.get(unique_id)
            if task is None:
                continue
            self._registry.packages[unique_id] = task.model_copy(
                update={
                    "kwargs_non_parallel": kwargs.get("kwargs_non_parallel"),
                    "kwargs_parallel": kwargs.get("kwargs_parallel"),
                }
            )

    def load_from_dict(self, data: dict) -> None:
        """Replace the registry from a dict produced by :meth:`to_dict`."""
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


tasks_registry = TasksRegistry()
