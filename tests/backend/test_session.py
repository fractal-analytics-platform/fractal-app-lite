"""Tests for whole-session persistence (bundled ``state.json``).

These exercise :mod:`backend.session` without any UI import. The ``registry``
fixture isolates the global ``tasks_registry`` singleton.
"""

import json

import pytest

from backend import session
from backend.state import AppState, RunRecord, WorkflowRunRecord
from fractal_lite import Dataset, Workflow, ZarrUrl, _collect


def _app_state() -> AppState:
    dataset = Dataset(
        name="my_dataset",
        zarr_dir="/z",
        zarr_urls=[
            # Mixed attribute value-types that CSV would coerce but JSON preserves.
            ZarrUrl(url="/z/a", attributes={"plate": "p1", "well": 2, "is3D": True}),
            ZarrUrl(url="/z/b", attributes={"plate": "p1"}, hidden=True),
        ],
    )
    history = [
        RunRecord(
            index=1,
            task_name="convert",
            filters=[("plate", "p1")],
            kwargs_non_parallel={"level": 2},
            kwargs_parallel=None,
            summary="+2 images (2 total)",
        ),
        RunRecord(
            index=2,
            task_name="segment",
            filters=[],
            kwargs_non_parallel=None,
            kwargs_parallel={"threshold": 5},
            summary="cancelled",
            status="cancelled",
        ),
    ]
    workflow_history = [
        WorkflowRunRecord(
            index=1,
            name="My WF",
            summary="2 step(s): 0 → 2 images (2 visible)",
            payload={"name": "My WF", "description": None, "steps": []},
            start_task=0,
            end_task=None,
        ),
    ]
    return AppState(
        dataset=dataset,
        run_history=history,
        workflow_history=workflow_history,
        max_workers=4,
    )


def test_session_round_trip(registry, tmp_path):
    src = _app_state()
    path = tmp_path / "state.json"
    session.save_session(path, state=src)

    dst = AppState()
    session.load_session(path, state=dst)

    got, want = dst.dataset, src.dataset
    assert got is not None and want is not None
    assert got.model_dump() == want.model_dump()
    # RunRecord dataclasses compare by value; filters restored as tuples.
    assert dst.run_history == src.run_history
    assert dst.run_history[0].filters == [("plate", "p1")]
    # WorkflowRunRecord dataclasses also compare by value.
    assert dst.workflow_history == src.workflow_history
    assert dst.workflow_history[0].name == "My WF"
    assert dst.max_workers == 4


def test_session_dataset_none_round_trips(registry, tmp_path):
    src = AppState(dataset=None, run_history=[], max_workers=1)
    path = tmp_path / "state.json"
    session.save_session(path, state=src)

    dst = AppState(dataset=Dataset(name="stale", zarr_dir="/z"))
    session.load_session(path, state=dst)

    assert dst.dataset is None
    assert dst.run_history == []


def test_session_includes_registry_and_reloads(registry):
    bundle = session.session_to_dict(_app_state())
    assert "registry" in bundle
    expected = {t.task.name for t in registry.tasks}

    # Wipe the registry, then prove apply restores it from the bundle.
    registry.load_from_dict({"packages": {}, "sources": [], "collection_dir": "."})
    assert registry.tasks == []
    session.apply_session_dict(bundle, state=AppState())
    assert {t.task.name for t in registry.tasks} == expected


def test_apply_rejects_unknown_version():
    with pytest.raises(ValueError, match="Unsupported session version"):
        session.apply_session_dict({"version": 999}, state=AppState())


# Large enough that, if persisted, it would dominate the bundle.
_BIG_SCHEMA = {"properties": {"x": {"description": "blah " * 400}}}
_SCHEMA_SENTINEL = _BIG_SCHEMA["properties"]["x"]["description"]


def _register_dir_task(registry, tmp_path, monkeypatch):
    """Collect a directory task carrying a large args schema into ``registry``."""
    # Avoid real pixi calls during collection / version refresh.
    monkeypatch.setattr(_collect, "_version_from_pixi_env", lambda start: "1.0.0")
    monkeypatch.setattr(_collect, "_recompute_version", lambda src: "1.0.0")
    pkg = tmp_path / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__FRACTAL_MANIFEST__.json").write_text(
        json.dumps(
            {
                "manifest_version": "2",
                "task_list": [
                    {
                        "type": "parallel",
                        "name": "Big Task",
                        "executable_parallel": "exec.py",
                        "args_schema_parallel": _BIG_SCHEMA,
                    }
                ],
            }
        )
    )
    registry.collect_from_directory(pkg)
    return registry.tasks[0]


def test_registry_saved_sources_only_and_rebuilt(registry, tmp_path, monkeypatch):
    task = _register_dir_task(registry, tmp_path, monkeypatch)
    state = AppState(workflow=Workflow(name="WF", task_list=[task]))

    path = tmp_path / "state.json"
    session.save_session(path, state=state)
    raw = path.read_text()

    # The large schema is not persisted anywhere (registry, workflow, or history).
    assert _SCHEMA_SENTINEL not in raw
    bundle = json.loads(raw)
    # Registry is sources-only — packages are omitted, sources are kept.
    assert "packages" not in bundle["registry"]
    assert bundle["registry"]["sources"]

    # Wipe the registry, then load: packages + schemas rebuild from the sources.
    registry.load_from_dict(
        {"packages": {}, "sources": [], "collection_dir": str(tmp_path)}
    )
    assert registry.tasks == []

    dst = AppState()
    session.load_session(path, state=dst)

    assert {t.task.name for t in registry.tasks} == {"Big Task"}
    assert registry.get_task(task.unique_id).task.args_schema_parallel == _BIG_SCHEMA
    # The current workflow's task is re-resolved to its real schema, not the blank.
    assert dst.workflow.task_list[0].task.args_schema_parallel == _BIG_SCHEMA


def test_registry_ignores_task_kwargs(registry, tmp_path, monkeypatch):
    """The registry holds templates only — task arguments are never stored."""
    task = _register_dir_task(registry, tmp_path, monkeypatch)
    registry.add_task(
        task.model_copy(update={"kwargs_parallel": {"threshold": 7}}), overwrite=True
    )

    stored = registry.get_task(task.unique_id)
    assert stored.kwargs_parallel is None
    assert stored.kwargs_non_parallel is None


def test_long_summary_is_truncated(registry):
    long = "x" * (session.MAX_SUMMARY_CHARS + 5000)
    state = AppState(
        run_history=[
            RunRecord(
                index=1,
                task_name="boom",
                filters=[],
                kwargs_non_parallel=None,
                kwargs_parallel=None,
                summary=long,
                status="failed",
            )
        ]
    )
    bundle = session.session_to_dict(state)
    saved = bundle["run_history"][0]["summary"]
    assert len(saved) < len(long)
    assert "elided" in saved
