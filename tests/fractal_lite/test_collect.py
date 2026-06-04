"""Tests for task collection and the TasksRegistry singleton."""

import json
from pathlib import Path

import pytest

from fractal_lite import _collect
from fractal_lite._collect import (
    _normalize_version,
    _parse_github_repo,
    _version_from_artifact_name,
    collect_from_dir,
    collect_from_gitrelease,
    collect_from_targz,
    find_manifest_file,
)
from fractal_lite._tasks import (
    DirectoryTaskSource,
    GitReleaseTaskSource,
    Task,
)

MANIFEST = "__FRACTAL_MANIFEST__.json"

_PARALLEL_TASK = {
    "type": "parallel",
    "name": "Supported Parallel",
    "executable_parallel": "exec.py",
    "args_schema_parallel": {},
}
_UNSUPPORTED_TASK = {
    "type": "non_parallel",
    "name": "Unsupported NonParallel",
    "executable_non_parallel": "exec.py",
    "args_schema_non_parallel": {},
}


def _write_manifest(directory: Path, task_list: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / MANIFEST).write_text(
        json.dumps({"manifest_version": "2", "task_list": task_list})
    )


def _sample_task(tmp_path: Path) -> Task:
    return Task(
        task=_PARALLEL_TASK,
        source_info=DirectoryTaskSource(
            path=tmp_path / "pkg.tar.gz", source_location=tmp_path, package_id="pkg"
        ),
    )


# --- find_manifest_file ---------------------------------------------------- #


def test_find_manifest_file_found(tmp_path):
    _write_manifest(tmp_path, [_PARALLEL_TASK])
    assert find_manifest_file(tmp_path) == tmp_path / MANIFEST


def test_find_manifest_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_manifest_file(tmp_path)


def test_find_manifest_file_multiple(tmp_path):
    _write_manifest(tmp_path, [_PARALLEL_TASK])
    _write_manifest(tmp_path / "nested", [_PARALLEL_TASK])
    with pytest.raises(FileExistsError):
        find_manifest_file(tmp_path)


# --- collection ------------------------------------------------------------ #


def test_collect_reads_input_output_types(tmp_path):
    """input_types and output_types from the manifest land on the task model."""
    pkg = tmp_path / "pkg"
    _write_manifest(
        pkg,
        [
            {
                "type": "parallel",
                "name": "With Types",
                "executable_parallel": "exec.py",
                "args_schema_parallel": {},
                "input_types": {"is_3D": True},
                "output_types": {"is_3D": False},
            },
            {
                "type": "parallel",
                "name": "Without Types",
                "executable_parallel": "exec.py",
                "args_schema_parallel": {},
            },
        ],
    )
    tasks = collect_from_dir(pkg, collection_dir=tmp_path / "collected")
    by_name = {t.task.name: t.task for t in tasks}

    assert by_name["With Types"].input_types == {"is_3D": True}
    assert by_name["With Types"].output_types == {"is_3D": False}
    assert by_name["Without Types"].input_types == {}
    assert by_name["Without Types"].output_types == {}


def test_collect_skips_unsupported_types(tmp_path, caplog):
    pkg = tmp_path / "pkg"
    _write_manifest(pkg, [_PARALLEL_TASK, _UNSUPPORTED_TASK])
    tasks = collect_from_dir(pkg, collection_dir=tmp_path / "collected")
    names = {t.task.name for t in tasks}
    assert names == {"Supported Parallel"}
    assert "is not supported" in caplog.text


def test_collect_from_targz_parses_converters(converters_targz, tmp_path):
    tasks = collect_from_targz(converters_targz, collection_dir=tmp_path / "collected")
    names = {t.task.name for t in tasks}
    assert "Convert Evident ScanR Plate to OME-Zarr" in names
    assert all(t.task.type == "converter_compound" for t in tasks)
    # Version is parsed from the tarball filename (fractal_uzh_converters-0.5.2).
    assert all(t.version == "0.5.2" for t in tasks)


def test_collect_from_dir_version_from_pixi_env(tmp_path, monkeypatch):
    """The local-directory version comes from the (stubbed) pixi env query."""
    monkeypatch.setattr(_collect, "_version_from_pixi_env", lambda start: "1.2.3")
    pkg = tmp_path / "pkg"
    _write_manifest(pkg, [_PARALLEL_TASK])
    tasks = collect_from_dir(pkg, collection_dir=tmp_path / "collected")
    assert all(t.version == "1.2.3" for t in tasks)


def test_recollect_from_source_preserves_package_id(tmp_path, monkeypatch):
    """Re-collecting a stored source keeps its original ``package_id``.

    Tarball packages are stored as a ``DirectoryTaskSource`` whose ``package_id`` is
    the tarball name (not ``local:*``); re-collection must preserve it so a task's
    ``unique_id`` stays stable across save/load.
    """
    monkeypatch.setattr(_collect, "_version_from_pixi_env", lambda start: "1.0.0")
    pkg = tmp_path / "pkg"
    _write_manifest(pkg, [_PARALLEL_TASK])
    src = DirectoryTaskSource(
        path=tmp_path / "fractal_demo-1.0.0.tar.gz",
        source_location=pkg,
        package_id="fractal_demo-1.0.0.tar.gz",
    )
    tasks = _collect.collect_from_source_info(src, tmp_path / "collected")
    assert tasks
    assert all(t.package_id == "fractal_demo-1.0.0.tar.gz" for t in tasks)


# --- version helpers ------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("v0.5.2", "0.5.2"),
        ("0.6.0", "0.6.0"),
        ("V1.2", "1.2"),
        ("  v2.0.0  ", "2.0.0"),
        ("release-3.4.5", "3.4.5"),
        ("", None),
        (None, None),
        ("latest", None),
    ],
)
def test_normalize_version(raw, expected):
    assert _normalize_version(raw) == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("pkg-1.2.3.tar.gz", "1.2.3"),
        ("fractal_lif_converters-0.6.0.tar.gz", "0.6.0"),
        ("fractal_uzh_converters-0.5.2", "0.5.2"),
        ("no-version-here.tar.gz", None),
    ],
)
def test_version_from_artifact_name(name, expected):
    assert _version_from_artifact_name(name) == expected


# --- git release ----------------------------------------------------------- #


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/owner/repo", ("owner", "repo")),
        ("https://github.com/owner/repo/", ("owner", "repo")),
        ("https://github.com/owner/repo.git", ("owner", "repo")),
        (
            "https://github.com/owner/repo/releases/download/v1.0/pkg-1.0.tar.gz",
            ("owner", "repo"),
        ),
    ],
)
def test_parse_github_repo(url, expected):
    assert _parse_github_repo(url) == expected


def test_parse_github_repo_rejects_non_github():
    with pytest.raises(ValueError):
        _parse_github_repo("https://gitlab.com/owner/repo")


def test_collect_from_gitrelease(converters_targz, tmp_path, monkeypatch):
    """The asset resolver is stubbed to point at the local converters tarball,
    so the download path copies it instead of hitting GitHub."""
    repo_url = "https://github.com/fractal-analytics-platform/fractal-uzh-converters"

    def fake_resolve(owner, repo, tag):
        assert (owner, repo) == ("fractal-analytics-platform", "fractal-uzh-converters")
        return (converters_targz.as_uri(), converters_targz.name, "v0.5.2")

    monkeypatch.setattr(_collect, "_resolve_release_asset", fake_resolve)

    tasks = collect_from_gitrelease(
        repo_url, tag="v0.5.2", collection_dir=tmp_path / "collected"
    )
    assert "Convert Evident ScanR Plate to OME-Zarr" in {t.task.name for t in tasks}
    for t in tasks:
        assert isinstance(t.source_info, GitReleaseTaskSource)
        assert t.source_info.repo_url == repo_url
        assert t.source_info.tag == "v0.5.2"
        assert t.source_info.version == "0.5.2"
        assert t.package_id == "fractal-uzh-converters@v0.5.2"
        # pkg_name is the distribution name from pyproject (matches the index).
        assert t.pkg_name == "fractal-uzh-converters"


# --- TasksRegistry --------------------------------------------------------- #


def test_registry_add_get_and_duplicate(registry, tmp_path):
    task = _sample_task(tmp_path)
    registry.add_task(task)
    # The registry stores a normalized copy (templates carry no kwargs), so
    # compare by value rather than identity.
    assert registry.get_task("Supported Parallel [pkg]") == task
    with pytest.raises(ValueError, match="already exists"):
        registry.add_task(task)
    # overwrite replaces silently.
    registry.add_task(task, overwrite=True)


def test_registry_same_name_different_package_coexist(registry, tmp_path):
    """Tasks sharing a name but from different packages get distinct unique_ids."""
    a = Task(
        task=_PARALLEL_TASK,
        source_info=DirectoryTaskSource(
            path=tmp_path / "a.tar.gz",
            source_location=tmp_path / "a",
            package_id="pkg_a",
        ),
    )
    b = Task(
        task=_PARALLEL_TASK,
        source_info=DirectoryTaskSource(
            path=tmp_path / "b.tar.gz",
            source_location=tmp_path / "b",
            package_id="pkg_b",
        ),
    )
    registry.add_task(a)
    registry.add_task(b)
    assert registry.get_task("Supported Parallel [pkg_a]") == a
    assert registry.get_task("Supported Parallel [pkg_b]") == b
    assert len(registry.tasks) == 2


def test_registry_get_missing_raises(registry):
    with pytest.raises(KeyError):
        registry.get_task("nope")


def test_registry_dump_load_round_trip(registry, tmp_path, monkeypatch):
    # The dump is sources-only; packages are rebuilt from the sources on load, so
    # round-trip a real, re-collectable directory (stub the pixi version probe).
    monkeypatch.setattr(_collect, "_version_from_pixi_env", lambda start: "1.0.0")
    pkg = tmp_path / "pkg"
    _write_manifest(pkg, [_PARALLEL_TASK])
    registry.collect_from_directory(pkg)
    unique_id = registry.tasks[0].unique_id

    out = tmp_path / "registry.json"
    registry.dump_to_json(out)
    # Sources-only: the packages (and their schemas) are not persisted.
    assert "packages" not in json.loads(out.read_text())

    registry.load_from_json(out)
    assert registry.get_task(unique_id).task.name == "Supported Parallel"


def test_load_recomputes_version(registry, tmp_path, monkeypatch):
    """A load re-derives each source's version instead of trusting the dumped value."""
    task = Task(
        task=_PARALLEL_TASK,
        source_info=DirectoryTaskSource(
            # A real directory (no .tar.gz) -> version comes from the pixi env.
            path=tmp_path / "pkg",
            source_location=tmp_path / "pkg",
            package_id="pkg",
            version="1.0.0",
        ),
    )
    registry.add_task(task)
    out = tmp_path / "registry.json"
    registry.dump_to_json(out)

    # The locally-installed package has since been upgraded.
    monkeypatch.setattr(_collect, "_version_from_pixi_env", lambda start: "2.0.0")
    # load_from_dict refreshes versions without re-collecting (no source on disk).
    registry.load_from_dict(json.loads(out.read_text()))

    # The stored sources are refreshed, so a later recollect starts from 2.0.0.
    assert registry._registry.sources
    assert all(s.version == "2.0.0" for s in registry._registry.sources)


# --- Task.pyproject_path --------------------------------------------------- #


def test_pyproject_path_resolves_ancestor(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    task = Task(
        task=_PARALLEL_TASK,
        source_info=DirectoryTaskSource(
            path=tmp_path / "p.tar.gz", source_location=src, package_id="pkg"
        ),
    )
    assert task.pyproject_path == tmp_path / "pyproject.toml"
