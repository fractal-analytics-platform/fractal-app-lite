"""Tests for input-/output-type enforcement in ``Workflow.run``.

The pure helpers (``ZarrUrl.matches_input_types`` / ``Dataset.with_output_types``)
are tested directly. The workflow-level tests wrap a task in a ``Task`` and
monkeypatch the subprocess helpers (as in ``test_tasks_run.py``) so only the
type-enforcement logic is exercised.
"""

from fractal_lite import Dataset
from fractal_lite import _tasks as tasks_mod
from fractal_lite import _workflow as workflow_mod
from fractal_lite._dataset import ZarrUrl
from fractal_lite._filters import TypeFilter
from fractal_lite._tasks import (
    ConverterNonParallelTask,
    DirectoryTaskSource,
    ParallelTask,
    Task,
)
from fractal_lite._workflow import Workflow


def _dataset(urls=()) -> Dataset:
    return Dataset(name="ds", zarr_dir="/z", zarr_urls=[ZarrUrl(**u) for u in urls])


def _by_url(ds: Dataset) -> dict[str, ZarrUrl]:
    return {zu.url: zu for zu in ds.zarr_urls}


def _wrap(task, tmp_path) -> Task:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    return Task(
        task=task,
        source_info=DirectoryTaskSource(
            path=tmp_path / "p.tar.gz", source_location=tmp_path, package_id="pkg"
        ),
    )


# --- ZarrUrl.matches_input_types -------------------------------------------


def test_matches_input_types_match_mismatch_and_missing():
    matching = ZarrUrl(url="/z/a", attributes={}, types={"is_3D": True})
    differing = ZarrUrl(url="/z/b", attributes={}, types={"is_3D": False})
    missing = ZarrUrl(url="/z/c", attributes={}, types={})

    assert matching.matches_input_types({"is_3D": True}) is True
    assert differing.matches_input_types({"is_3D": True}) is False
    # A missing key counts as a match (still run on).
    assert missing.matches_input_types({"is_3D": True}) is True


def test_matches_input_types_multi_key_is_and():
    zu = ZarrUrl(url="/z/a", attributes={}, types={"is_3D": True, "registered": True})
    assert zu.matches_input_types({"is_3D": True, "registered": True}) is True
    # One differing key fails the whole match.
    assert zu.matches_input_types({"is_3D": True, "registered": False}) is False


# --- Dataset.with_output_types ---------------------------------------------


def test_with_output_types_empty_is_noop():
    ds = _dataset([{"url": "/z/a", "attributes": {}, "types": {"is_3D": True}}])
    assert ds.with_output_types(["/z/a"], [], {}) is ds


def test_with_output_types_assigns_and_hides():
    ds = _dataset(
        [
            # Originals the task ran on.
            {"url": "/z/3a", "attributes": {}, "types": {"is_3D": True, "ch": True}},
            {"url": "/z/3b", "attributes": {}, "types": {"is_3D": True}},
            # Produced (already folded in with the output value).
            {"url": "/z/2a", "attributes": {}, "types": {"is_3D": False}},
            # Untouched image (not run on, not produced).
            {"url": "/z/other", "attributes": {}, "types": {"is_3D": False}},
        ]
    )
    out = _by_url(ds.with_output_types(["/z/3a", "/z/3b"], ["/z/2a"], {"is_3D": False}))

    # Produced -> output value, visible.
    assert out["/z/2a"].types == {"is_3D": False}
    assert out["/z/2a"].hidden is False
    # Run-but-not-produced -> opposite value, hidden; other keys untouched.
    assert out["/z/3a"].types == {"is_3D": True, "ch": True}
    assert out["/z/3a"].hidden is True
    assert out["/z/3b"].hidden is True
    # Outside the touched set -> entirely untouched.
    assert out["/z/other"].hidden is False
    assert out["/z/other"].types == {"is_3D": False}


def test_with_output_types_no_produced_assigns_to_run_urls():
    ds = _dataset([{"url": "/z/a", "attributes": {}, "types": {"is_3D": True}}])
    out = _by_url(ds.with_output_types(["/z/a"], [], {"is_3D": False}))
    # No updates: the input image gets the output value and stays visible.
    assert out["/z/a"].types == {"is_3D": False}
    assert out["/z/a"].hidden is False


def test_with_output_types_never_unhides():
    ds = _dataset(
        [{"url": "/z/a", "attributes": {}, "types": {"is_3D": False}, "hidden": True}]
    )
    out = _by_url(ds.with_output_types(["/z/a"], ["/z/a"], {"is_3D": False}))
    # Produced + matching value, but an already-hidden image is never revealed.
    assert out["/z/a"].hidden is True


# --- Workflow.run integration ----------------------------------------------


def test_workflow_input_selection_and_output_types(monkeypatch, tmp_path):
    captured = {}

    def fake_p(per_item_kwargs, *a, **_):
        captured["items"] = per_item_kwargs
        return [
            {"image_list_updates": [{"zarr_url": f"{it['zarr_url']}/proj"}]}
            for it in per_item_kwargs
        ]

    monkeypatch.setattr(tasks_mod, "_run_parallel_task", fake_p)

    ds = _dataset(
        [
            {"url": "/z/3a", "attributes": {}, "types": {"is_3D": True}},
            {"url": "/z/2a", "attributes": {}, "types": {"is_3D": False}},
            {"url": "/z/missing", "attributes": {}, "types": {}},
        ]
    )
    task = _wrap(
        ParallelTask(
            type="parallel",
            name="proj",
            executable_parallel="exec.py",
            args_schema_parallel={},
            input_types={"is_3D": True},
            output_types={"is_3D": False},
        ),
        tmp_path,
    )
    out = _by_url(Workflow(task_list=[task]).run(ds))

    # Input-types: 3D and the missing-key image run; the 2D image is excluded.
    assert [it["zarr_url"] for it in captured["items"]] == ["/z/3a", "/z/missing"]
    # Produced 2D projections are visible with the output value.
    assert out["/z/3a/proj"].types == {"is_3D": False}
    assert out["/z/3a/proj"].hidden is False
    assert out["/z/missing/proj"].hidden is False
    # Originals the task ran on get the opposite value and are hidden.
    assert out["/z/3a"].types == {"is_3D": True} and out["/z/3a"].hidden is True
    assert out["/z/missing"].types == {"is_3D": True}
    assert out["/z/missing"].hidden is True
    # The input-type-excluded 2D image is untouched (no persisted hide).
    assert out["/z/2a"].types == {"is_3D": False}
    assert out["/z/2a"].hidden is False


def test_workflow_no_update_assigns_output_in_place(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tasks_mod, "_run_parallel_task", lambda items, *a, **_: [None for _ in items]
    )
    ds = _dataset([{"url": "/z/a", "attributes": {}, "types": {"is_3D": True}}])
    task = _wrap(
        ParallelTask(
            type="parallel",
            name="t",
            executable_parallel="exec.py",
            args_schema_parallel={},
            output_types={"is_3D": False},
        ),
        tmp_path,
    )
    out = _by_url(Workflow(task_list=[task]).run(ds))
    assert out["/z/a"].types == {"is_3D": False}
    assert out["/z/a"].hidden is False


def test_workflow_new_output_key(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tasks_mod,
        "_run_parallel_task",
        lambda items, *a, **_: [
            {"image_list_updates": [{"zarr_url": f"{it['zarr_url']}/o"}]}
            for it in items
        ],
    )
    ds = _dataset([{"url": "/z/a", "attributes": {}, "types": {}}])
    task = _wrap(
        ParallelTask(
            type="parallel",
            name="t",
            executable_parallel="exec.py",
            args_schema_parallel={},
            output_types={"registered": True},
        ),
        tmp_path,
    )
    out = _by_url(Workflow(task_list=[task]).run(ds))
    # Brand-new key: produced gets True/visible, the input gets False/hidden.
    assert out["/z/a/o"].types == {"registered": True}
    assert out["/z/a/o"].hidden is False
    assert out["/z/a"].types == {"registered": False}
    assert out["/z/a"].hidden is True


def test_workflow_converter_leaves_existing_images_untouched(monkeypatch, tmp_path):
    def fake_np(kwargs, *a, **_):
        return {"image_list_updates": [{"zarr_url": "/z/new", "attributes": {}}]}

    monkeypatch.setattr(tasks_mod, "_run_non_parallel_task", fake_np)

    ds = _dataset([{"url": "/z/old", "attributes": {}, "types": {"is_3D": False}}])
    task = _wrap(
        ConverterNonParallelTask(
            type="converter_non_parallel",
            name="conv",
            executable_non_parallel="exec.py",
            args_schema_non_parallel={},
            output_types={"is_3D": True},
        ),
        tmp_path,
    )
    out = _by_url(Workflow(task_list=[task]).run(ds))
    # Converter consumes zarr_dir, so pre-existing images are not flipped/hidden.
    assert out["/z/old"].types == {"is_3D": False}
    assert out["/z/old"].hidden is False
    # The produced image carries the output type.
    assert out["/z/new"].types == {"is_3D": True}
    assert out["/z/new"].hidden is False


# --- isolation == workflow -------------------------------------------------


def test_task_run_in_isolation_matches_single_step_workflow(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tasks_mod,
        "_run_parallel_task",
        lambda items, *a, **_: [
            {"image_list_updates": [{"zarr_url": f"{it['zarr_url']}/proj"}]}
            for it in items
        ],
    )
    urls = [
        {"url": "/z/3a", "attributes": {}, "types": {"is_3D": True}},
        {"url": "/z/2a", "attributes": {}, "types": {"is_3D": False}},
    ]
    task = _wrap(
        ParallelTask(
            type="parallel",
            name="proj",
            executable_parallel="exec.py",
            args_schema_parallel={},
            input_types={"is_3D": True},
            output_types={"is_3D": False},
        ),
        tmp_path,
    )
    # Running the task directly and as a single-step workflow must agree exactly.
    isolated = task.run(_dataset(urls))
    workflow = Workflow(task_list=[task]).run(_dataset(urls))
    assert isolated.model_dump() == workflow.model_dump()
    # And it actually did the type enforcement (not a trivial no-op match).
    out = _by_url(isolated)
    assert out["/z/3a"].hidden is True
    assert out["/z/3a/proj"].types == {"is_3D": False}
    assert out["/z/2a"].hidden is False


# --- serialization ---------------------------------------------------------


def _export_task(tmp_path) -> Task:
    """A ``Task`` carrying the identity + kwargs the Fractal format records."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    inner = ParallelTask(
        type="parallel",
        name="My Task",
        executable_parallel="exec.py",
        args_schema_parallel={},
        meta_parallel={"cpus_per_task": 2},
    )
    return Task(
        task=inner,
        source_info=DirectoryTaskSource(
            path=tmp_path / "p.tar.gz",
            source_location=tmp_path,
            package_id="local:x",
            pkg_name="fractal-tasks-core",
            version="2.0.0",
        ),
        kwargs_parallel={"level": 1},
        kwargs_non_parallel=None,
    )


def test_plain_json_round_trip_preserves_filters(tmp_path):
    wf = Workflow(
        name="W",
        description="d",
        task_list=[_export_task(tmp_path), TypeFilter(key="is_3D", value=True)],
    )
    restored = Workflow.from_json(wf.to_json())
    # Lossless: both task and filter steps survive intact.
    assert restored.model_dump() == wf.model_dump()


def test_to_fractal_dict_shape_and_drops_filters(tmp_path):
    wf = Workflow(
        name="W",
        description="d",
        task_list=[_export_task(tmp_path), TypeFilter(key="is_3D", value=True)],
    )
    out = wf.to_fractal_dict()
    assert out["name"] == "W"
    assert out["description"] == "d"
    # Filter step dropped; only the task remains.
    assert len(out["task_list"]) == 1
    entry = out["task_list"][0]
    assert entry["task"] == {
        "pkg_name": "fractal-tasks-core",
        "version": "2.0.0",
        "name": "My Task",
    }
    assert entry["meta_parallel"] == {"cpus_per_task": 2}
    # A parallel task has no non-parallel phase.
    assert entry["meta_non_parallel"] is None
    assert entry["args_parallel"] == {"level": 1}
    assert entry["args_non_parallel"] is None
    assert entry["type_filters"] == {}
    assert entry["description"] is None
    assert entry["alias"] is None


def test_from_fractal_dict_resolves_and_attaches_kwargs(monkeypatch, tmp_path):
    resolved = _export_task(tmp_path)
    calls = []

    def fake_resolve(pkg_name, version, name):
        calls.append((pkg_name, version, name))
        return resolved

    monkeypatch.setattr(workflow_mod, "_resolve_task", fake_resolve)

    data = {
        "name": "W",
        "description": None,
        "task_list": [
            {
                "args_non_parallel": {"a": 1},
                "args_parallel": {"b": 2},
                "task": {
                    "pkg_name": "fractal-tasks-core",
                    "version": "2.0.0",
                    "name": "My Task",
                },
            }
        ],
    }
    wf = Workflow.from_fractal_dict(data)

    assert calls == [("fractal-tasks-core", "2.0.0", "My Task")]
    assert len(wf.task_list) == 1
    step = wf.task_list[0]
    assert isinstance(step, Task)
    # args_* land on the task's kwargs; the resolved task is left otherwise intact.
    assert step.kwargs_non_parallel == {"a": 1}
    assert step.kwargs_parallel == {"b": 2}
    assert step.name == "My Task"


def test_from_fractal_json_matches_from_fractal_dict(monkeypatch, tmp_path):
    monkeypatch.setattr(
        workflow_mod, "_resolve_task", lambda *a: _export_task(tmp_path)
    )
    data = {
        "name": "W",
        "description": None,
        "task_list": [
            {
                "args_non_parallel": None,
                "args_parallel": {"b": 2},
                "task": {
                    "pkg_name": "fractal-tasks-core",
                    "version": "2.0.0",
                    "name": "My Task",
                },
            }
        ],
    }
    import json

    wf = Workflow.from_fractal_json(json.dumps(data))
    assert wf.task_list[0].kwargs_parallel == {"b": 2}
