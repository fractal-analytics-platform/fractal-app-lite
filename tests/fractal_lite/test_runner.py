"""Tests for the ``_runner`` orchestration (Task.run stubbed).

The runner builds on ``Task.run`` (the execution seam) and ``Filter.run``. We stub
``Task.run`` to return controlled datasets so the tests exercise the runner's own
logic — transient filtering, new-image folding, dataset threading, history recording,
status/summary mapping, and the deep-copy workflow snapshot — without spawning ``pixi``.
"""

import json

import pytest

from fractal_lite import (
    Dataset,
    Project,
    RunCancelled,
    ZarrUrl,
    run_task,
    run_workflow,
)
from fractal_lite._filters import AttributeFilter
from fractal_lite._tasks import Task

_MANIFEST = {
    "manifest_version": "2",
    "task_list": [
        {
            "type": "parallel",
            "name": "Sample",
            "executable_parallel": "exec.py",
            "args_schema_parallel": {},
        }
    ],
}


def _register_task(registry, tmp_path) -> Task:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__FRACTAL_MANIFEST__.json").write_text(json.dumps(_MANIFEST))
    registry.collect_from_directory(pkg)
    return registry.tasks[0]


def _project(tmp_path, registry, *, n_images: int = 1) -> Project:
    zarr_dir = str(tmp_path / "zarr")
    project = Project.create(tmp_path / "proj", name="P", zarr_dir=zarr_dir)
    # The runner reads tasks off ``project.registry``; use the test's registry.
    project.registry = registry
    project.dataset = Dataset(
        name="P",
        zarr_dir=zarr_dir,
        zarr_urls=[
            ZarrUrl(url=f"{zarr_dir}/img{i}.zarr", attributes={"well": "A1"})
            for i in range(n_images)
        ],
    )
    return project


def _appending_run(n_new: int = 1):
    """A fake ``Task.run`` that appends ``n_new`` new images and records a metric."""

    def fake_run(
        self,
        dataset,
        *,
        on_output=None,
        cancellation=None,
        max_workers=1,
        metrics=None,
    ):
        if on_output is not None:
            on_output("task running")
        if metrics is not None:
            metrics.record_item(0.01)
        new = [
            ZarrUrl(url=f"{dataset.zarr_dir}/new{i}.zarr", attributes={})
            for i in range(n_new)
        ]
        return dataset.model_copy(update={"zarr_urls": [*dataset.zarr_urls, *new]})

    return fake_run


# --- run_task --------------------------------------------------------------


def test_run_task_folds_new_images(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)
    monkeypatch.setattr(Task, "run", _appending_run(n_new=2))
    project = _project(tmp_path, registry, n_images=1)

    result = run_task(project, task.unique_id, None, None, [], [])

    # Two new images folded into the shared dataset (1 -> 3).
    assert len(project.dataset.zarr_urls) == 3
    assert result.status == "completed"
    assert result.summary == "+2 images (3 total)"
    assert result.total_seconds is not None
    assert result.mean_item_seconds is not None

    # One completed record, auto-indexed at 1.
    assert len(project.sandbox_history) == 1
    record = project.sandbox_history[0]
    assert record.index == 1
    assert record.task_name == task.unique_id
    assert record.status == "completed"


def test_run_task_captures_filters_and_kwargs(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)
    monkeypatch.setattr(Task, "run", _appending_run())
    project = _project(tmp_path, registry, n_images=1)

    run_task(
        project,
        task.unique_id,
        {"init": 1},
        {"par": 2},
        [("well", "A1"), ("", "ignored")],
        [("is_3D", True), ("", False)],
    )

    record = project.sandbox_history[0]
    # Empty-attribute/key filters are dropped; the rest are recorded.
    assert record.filters == [("well", "A1")]
    assert record.type_filters == [("is_3D", True)]
    assert record.kwargs_non_parallel == {"init": 1}
    assert record.kwargs_parallel == {"par": 2}


def test_run_task_transient_filters_dont_touch_shared_dataset(
    registry, tmp_path, monkeypatch
):
    task = _register_task(registry, tmp_path)
    monkeypatch.setattr(Task, "run", _appending_run())
    project = _project(tmp_path, registry, n_images=1)

    # A filter that matches nothing would deactivate the image on the working copy.
    run_task(project, task.unique_id, None, None, [("well", "Z9")], [])

    # The shared dataset's original image is untouched (still active).
    assert project.dataset.zarr_urls[0].active is True


def test_run_task_on_empty_dataset_is_allowed(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)
    monkeypatch.setattr(Task, "run", _appending_run())
    project = _project(tmp_path, registry, n_images=0)

    result = run_task(project, task.unique_id, None, None, [], [])

    assert result.status == "completed"
    assert result.summary == "+1 images (1 total)"


def test_run_task_cancelled(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)

    def cancel(self, *a, **k):
        raise RunCancelled

    monkeypatch.setattr(Task, "run", cancel)
    project = _project(tmp_path, registry, n_images=1)

    result = run_task(project, task.unique_id, None, None, [], [])

    assert result.status == "cancelled"
    assert result.summary == "cancelled"
    # Dataset untouched; a cancelled record is still written.
    assert len(project.dataset.zarr_urls) == 1
    assert project.sandbox_history[0].status == "cancelled"


def test_run_task_failed_records_and_reraises(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)

    def boom(self, *a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(Task, "run", boom)
    project = _project(tmp_path, registry, n_images=1)

    with pytest.raises(RuntimeError, match="kaboom"):
        run_task(project, task.unique_id, None, None, [], [])

    record = project.sandbox_history[0]
    assert record.status == "failed"
    assert record.summary == "failed: kaboom"


# --- run_workflow ----------------------------------------------------------


def test_run_workflow_threads_and_replaces_dataset(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)
    monkeypatch.setattr(Task, "run", _appending_run())
    project = _project(tmp_path, registry, n_images=1)
    project.workflow.add_step(task)
    project.workflow.add_step(task.model_copy())

    result = run_workflow(project)

    # Threaded through 2 steps: 1 -> 3 images, all visible.
    assert len(project.dataset.zarr_urls) == 3
    assert result.status == "completed"
    assert result.summary == "2 step(s): 1 → 3 images (3 visible)"

    assert len(project.workflow_history) == 1
    record = project.workflow_history[0]
    assert record.index == 1
    assert record.status == "completed"
    assert record.start_task == 0
    assert record.end_task is None
    assert record.workflow is not None


def test_run_workflow_runs_filter_steps(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)
    monkeypatch.setattr(Task, "run", _appending_run())
    project = _project(tmp_path, registry, n_images=1)
    # A filter that matches the image keeps it active; the task then appends one.
    project.workflow.add_step(AttributeFilter(attribute="well", value="A1"))
    project.workflow.add_step(task)

    result = run_workflow(project)

    assert result.status == "completed"
    assert "[step 0] Applying filter" in "\n".join(result.log)
    assert len(project.dataset.zarr_urls) == 2


def test_run_workflow_snapshot_is_deep_copied(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)
    monkeypatch.setattr(Task, "run", _appending_run())
    project = _project(tmp_path, registry, n_images=1)
    project.workflow.add_step(task)

    run_workflow(project)
    snapshot = project.workflow_history[0].workflow
    assert len(snapshot.task_list) == 1

    # Editing the live workflow must not mutate the recorded snapshot.
    project.workflow.add_step(task.model_copy())
    assert len(snapshot.task_list) == 1


def test_run_workflow_sub_range(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)
    calls: list[int] = []

    def counting_run(self, dataset, **k):
        calls.append(1)
        new = ZarrUrl(url=f"{dataset.zarr_dir}/n{len(calls)}.zarr", attributes={})
        return dataset.model_copy(update={"zarr_urls": [*dataset.zarr_urls, new]})

    monkeypatch.setattr(Task, "run", counting_run)
    project = _project(tmp_path, registry, n_images=1)
    for _ in range(3):
        project.workflow.add_step(task.model_copy())

    run_workflow(project, start_task=1, end_task=3)

    # Only steps [1, 3) ran (2 of the 3 task steps).
    assert len(calls) == 2
    record = project.workflow_history[0]
    assert record.start_task == 1
    assert record.end_task == 3
    assert record.summary == "2 step(s): 1 → 3 images (3 visible)"


def test_run_workflow_empty_steps_raises(registry, tmp_path):
    project = _project(tmp_path, registry, n_images=1)
    with pytest.raises(ValueError, match="No workflow steps to run"):
        run_workflow(project)


def test_run_workflow_cancelled(registry, tmp_path, monkeypatch):
    task = _register_task(registry, tmp_path)

    def cancel(self, *a, **k):
        raise RunCancelled

    monkeypatch.setattr(Task, "run", cancel)
    project = _project(tmp_path, registry, n_images=1)
    project.workflow.add_step(task)

    result = run_workflow(project)

    assert result.status == "cancelled"
    assert project.workflow_history[0].status == "cancelled"
    # Dataset is not replaced on cancel.
    assert len(project.dataset.zarr_urls) == 1
