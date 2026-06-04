"""Tests for the per-task-type ``execute()`` logic with the subprocess mocked.

The ``execute`` methods call the module-level ``_run_non_parallel_task`` /
``_run_parallel_task`` helpers, which spawn ``pixi``. We monkeypatch those so the
tests exercise pure kwargs/flattening logic without building any env. ``execute``
returns the flattened ``image_list_updates``; dataset folding and type
enforcement live in ``Task.run`` (covered in ``test_workflow.py``).
"""

from pathlib import Path

from fractal_lite import Dataset
from fractal_lite import _tasks as tasks_mod
from fractal_lite._dataset import ZarrUrl
from fractal_lite._tasks import (
    CompoundTask,
    ConverterCompoundTask,
    ConverterNonParallelTask,
    DirectoryTaskSource,
    ParallelTask,
    Task,
)

SRC = Path("/src")
PYPROJECT = Path("/src/pyproject.toml")


def _dataset(urls=()) -> Dataset:
    return Dataset(
        name="ds",
        zarr_dir="/z",
        zarr_urls=[ZarrUrl(**u) for u in urls],
    )


def test_converter_non_parallel_injects_zarr_dir_and_returns_updates(monkeypatch):
    captured = {}

    def fake_np(kwargs, executable, source_location, pyproject_path, **_):
        captured["kwargs"] = kwargs
        return {
            "image_list_updates": [
                {
                    "zarr_url": "/z/A/0",
                    "attributes": {"plate": "p1"},
                    "types": {"is_3D": False},
                }
            ]
        }

    monkeypatch.setattr(tasks_mod, "_run_non_parallel_task", fake_np)

    task = ConverterNonParallelTask(
        type="converter_non_parallel",
        name="conv",
        executable_non_parallel="exec.py",
        args_schema_non_parallel={},
    )
    # Converter ignores run_urls and reads zarr_dir.
    updates = task.execute("/z", [], {"acquisitions": ["x"]}, None, SRC, PYPROJECT)

    assert captured["kwargs"] == {"acquisitions": ["x"], "zarr_dir": "/z"}
    # execute returns the flattened image_list_updates verbatim.
    assert updates == [
        {"zarr_url": "/z/A/0", "attributes": {"plate": "p1"}, "types": {"is_3D": False}}
    ]


def test_parallel_runs_one_item_per_run_url(monkeypatch):
    captured = {}

    def fake_p(per_item_kwargs, executable, source_location, pyproject_path, **_):
        captured["items"] = per_item_kwargs
        return [None for _ in per_item_kwargs]

    monkeypatch.setattr(tasks_mod, "_run_parallel_task", fake_p)

    task = ParallelTask(
        type="parallel",
        name="par",
        executable_parallel="exec.py",
        args_schema_parallel={},
    )
    updates = task.execute("/z", ["/z/a"], None, {"threshold": 5}, SRC, PYPROJECT)

    # One item per run_url; kwargs_parallel are merged in.
    assert captured["items"] == [{"zarr_url": "/z/a", "threshold": 5}]
    # None results (in-place mutation) contribute no updates.
    assert updates == []


def test_compound_init_receives_run_urls_and_parallel_merges_items(monkeypatch):
    captured = {}

    def fake_np(kwargs, executable, source_location, pyproject_path, **_):
        captured["init"] = kwargs
        return {"parallelization_list": [{"zarr_url": "/z/a", "init_arg": 1}]}

    def fake_p(per_item_kwargs, executable, source_location, pyproject_path, **_):
        captured["items"] = per_item_kwargs
        return [{"image_list_updates": [{"zarr_url": "/z/a/0", "attributes": {}}]}]

    monkeypatch.setattr(tasks_mod, "_run_non_parallel_task", fake_np)
    monkeypatch.setattr(tasks_mod, "_run_parallel_task", fake_p)

    task = CompoundTask(
        type="compound",
        name="comp",
        executable_parallel="par.py",
        args_schema_parallel={},
        executable_non_parallel="init.py",
        args_schema_non_parallel={},
    )
    updates = task.execute("/z", ["/z/a"], {"level": 2}, {"sigma": 1}, SRC, PYPROJECT)

    # Init gets the selected run_urls plus zarr_dir and the user init kwargs.
    assert captured["init"] == {
        "level": 2,
        "zarr_urls": ["/z/a"],
        "zarr_dir": "/z",
    }
    # Parallel merges each parallelization-list item with kwargs_parallel.
    assert captured["items"] == [{"zarr_url": "/z/a", "init_arg": 1, "sigma": 1}]
    assert updates == [{"zarr_url": "/z/a/0", "attributes": {}}]


def test_converter_compound_init_receives_zarr_dir_only(monkeypatch):
    captured = {}

    def fake_np(kwargs, executable, source_location, pyproject_path, **_):
        captured["init"] = kwargs
        return {"parallelization_list": [{"zarr_url": "/z/a"}]}

    def fake_p(per_item_kwargs, executable, source_location, pyproject_path, **_):
        captured["items"] = per_item_kwargs
        return [{"image_list_updates": [{"zarr_url": "/z/a", "attributes": {}}]}]

    monkeypatch.setattr(tasks_mod, "_run_non_parallel_task", fake_np)
    monkeypatch.setattr(tasks_mod, "_run_parallel_task", fake_p)

    task = ConverterCompoundTask(
        type="converter_compound",
        name="conv_comp",
        executable_parallel="par.py",
        args_schema_parallel={},
        executable_non_parallel="init.py",
        args_schema_non_parallel={},
    )
    task.execute("/z", [], {"acquisitions": ["x"]}, None, SRC, PYPROJECT)

    # Converter init gets zarr_dir (not zarr_urls).
    assert captured["init"] == {"acquisitions": ["x"], "zarr_dir": "/z"}
    assert captured["items"] == [{"zarr_url": "/z/a"}]


def test_task_kwargs_precedence(monkeypatch, tmp_path):
    captured = {}

    def fake_np(kwargs, executable, source_location, pyproject_path, **_):
        captured["kwargs"] = kwargs
        return {"image_list_updates": []}

    monkeypatch.setattr(tasks_mod, "_run_non_parallel_task", fake_np)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

    task = Task(
        task=ConverterNonParallelTask(
            type="converter_non_parallel",
            name="conv",
            executable_non_parallel="exec.py",
            args_schema_non_parallel={},
        ),
        source_info=DirectoryTaskSource(
            path=tmp_path / "p.tar.gz", source_location=tmp_path, package_id="pkg"
        ),
        kwargs_non_parallel={"stored": True},
    )

    # No override -> stored kwargs are used.
    task.run(_dataset())
    assert captured["kwargs"] == {"stored": True, "zarr_dir": "/z"}

    # Explicit override wins over the stored kwargs.
    task.run(_dataset(), kwargs_non_parallel={"override": 1})
    assert captured["kwargs"] == {"override": 1, "zarr_dir": "/z"}
