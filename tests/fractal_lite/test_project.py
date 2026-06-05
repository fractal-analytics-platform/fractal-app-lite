"""Round-trip tests for the Project / History persistence layer."""

import json
import shutil

from fractal_lite import (
    Dataset,
    Project,
    SandboxRunRecord,
    WorkflowRunRecord,
    ZarrUrl,
)
from fractal_lite._history import MAX_SUMMARY_CHARS

_SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}}
_MANIFEST = {
    "manifest_version": "2",
    "task_list": [
        {
            "type": "parallel",
            "name": "Sample",
            "executable_parallel": "exec.py",
            "args_schema_parallel": _SCHEMA,
        }
    ],
}


def _register_task(registry, tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__FRACTAL_MANIFEST__.json").write_text(json.dumps(_MANIFEST))
    registry.collect_from_directory(pkg)
    return registry.tasks[0]


def _dataset(zarr_dir):
    return Dataset(
        name="ignored",  # not persisted; project name wins on load
        zarr_dir=str(zarr_dir),
        zarr_urls=[
            ZarrUrl(
                url=f"{zarr_dir}/img0.zarr",
                attributes={"well": "A1", "cycle": 2},
                types={"is_3D": True},
            )
        ],
    )


def test_project_round_trip(registry, tmp_path):
    task = _register_task(registry, tmp_path)
    assert task.task.args_schema_parallel == _SCHEMA  # non-empty before stripping

    zarr_dir = tmp_path / "zarr"
    proj_dir = tmp_path / "proj"
    project = Project.create(
        proj_dir, name="MyProject", zarr_dir=str(zarr_dir), max_workers=4
    )
    # The project persists/reloads its own registry; use the one holding the task.
    project.registry = registry

    project.dataset = _dataset(zarr_dir)
    project.workflow.add_step(task)
    long_summary = "x" * (MAX_SUMMARY_CHARS + 500)
    project.sandbox_history.add(
        SandboxRunRecord(task_name="Sample", summary=long_summary, status="completed")
    )
    project.workflow_history.add(
        WorkflowRunRecord(name="MyProject", summary="ok", workflow=project.workflow)
    )
    project.save()

    # Files written; CSV present because the dataset has an image.
    for fname in (
        "project.json",
        "table.csv",
        "workflow.json",
        "sandbox_history.json",
        "workflow_history.json",
        "registry.json",
    ):
        assert (proj_dir / fname).is_file(), fname

    # Schemas stripped on disk; summary truncated with an elision marker.
    wf_disk = json.loads((proj_dir / "workflow.json").read_text())
    assert wf_disk["task_list"][0]["task"]["args_schema_parallel"] == {}
    hist_disk = json.loads((proj_dir / "sandbox_history.json").read_text())
    saved_summary = hist_disk["records"][0]["summary"]
    assert len(saved_summary) <= MAX_SUMMARY_CHARS + 64
    assert "chars elided" in saved_summary

    # Move the directory to prove relative-path portability, then load.
    moved = tmp_path / "moved"
    shutil.move(str(proj_dir), str(moved))
    loaded = Project.load(moved)

    assert loaded.name == "MyProject"
    assert loaded.max_workers == 4
    assert loaded.zarr_dir == str(zarr_dir)

    # Dataset: name reset to project name; attributes & types round-trip.
    assert loaded.dataset.name == "MyProject"
    assert len(loaded.dataset.zarr_urls) == 1
    zu = loaded.dataset.zarr_urls[0]
    assert zu.attributes == {"well": "A1", "cycle": 2}
    assert zu.types == {"is_3D": True}

    # Workflow schemas re-resolved from the registry after load.
    step = loaded.workflow.task_list[0]
    assert step.task.args_schema_parallel == _SCHEMA

    # Histories: records, indices, and re-resolved workflow snapshot.
    assert len(loaded.sandbox_history) == 1
    assert loaded.sandbox_history[0].index == 1
    assert len(loaded.workflow_history) == 1
    wr = loaded.workflow_history[0]
    assert wr.index == 1
    assert wr.workflow.task_list[0].task.args_schema_parallel == _SCHEMA


def test_empty_project_round_trip(registry, tmp_path):
    proj_dir = tmp_path / "proj"
    project = Project.create(proj_dir, name="Empty", zarr_dir=str(tmp_path / "zarr"))
    project.save()
    # No images -> no CSV file.
    assert not (proj_dir / "table.csv").exists()

    loaded = Project.load(proj_dir)
    assert loaded.dataset.zarr_urls == []
    assert loaded.dataset.name == "Empty"
    assert len(loaded.workflow.task_list) == 0
    assert len(loaded.sandbox_history) == 0
