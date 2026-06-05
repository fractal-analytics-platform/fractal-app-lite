"""Tests for the workflow endpoints and the step-list <-> Workflow conversion.

Run with: ``pixi run -e dev test``. Uses the ``seeded_client`` fixture (one collected
package) so task steps resolve against the registry. State lives on a ``Project``
singleton; the fixtures open a fresh project (with an empty workflow) per test.
"""

import pytest
from fastapi.testclient import TestClient

from backend import state
from backend.main import app
from backend.schemas import WorkflowPayload, WorkflowStep
from backend.workflow_service import steps_to_workflow, workflow_to_payload
from fractal_lite import Project, tasks_registry
from fractal_lite._filters import AttributeFilter, TypeFilter
from fractal_lite._tasks import Task


def _open_project(tmp_path):
    state.set_project(
        Project.create(tmp_path / "proj", name="WF", zarr_dir=str(tmp_path / "z"))
    )


@pytest.fixture
def client(registry, tmp_path):
    # Each test starts from a fresh project with an empty workflow.
    _open_project(tmp_path)
    with TestClient(app) as c:
        yield c
    state.set_project(None)


@pytest.fixture
def seeded_client(registry, converters_targz, tmp_path):
    """A client whose registry has one collected package and an open project."""
    tasks_registry.collect_from_targz(converters_targz, overwrite=True)
    _open_project(tmp_path)
    with TestClient(app) as c:
        yield c
    state.set_project(None)


def test_empty_workflow_initially(client):
    res = client.get("/api/workflow").json()
    assert res["steps"] == []


def test_set_and_get_workflow_round_trips(seeded_client):
    uid = seeded_client.get("/api/tasks").json()[0]["unique_id"]
    payload = {
        "name": "My WF",
        "description": "demo",
        "steps": [
            {
                "kind": "task",
                "task_name": uid,
                "kwargs_non_parallel": {"overwrite": True},
            },
            {"kind": "filter", "filter_type": "type", "key": "is_3D", "value": True},
            {
                "kind": "filter",
                "filter_type": "attribute",
                "attribute": "well",
                "value": "A01",
            },
        ],
    }
    echoed = seeded_client.post("/api/workflow", json=payload).json()
    assert echoed["name"] == "My WF"
    assert [s["kind"] for s in echoed["steps"]] == ["task", "filter", "filter"]

    got = seeded_client.get("/api/workflow").json()
    assert got["steps"][0]["task_name"] == uid
    assert got["steps"][0]["kwargs_non_parallel"] == {"overwrite": True}
    assert got["steps"][1] == {
        "kind": "filter",
        "filter_type": "type",
        "key": "is_3D",
        "value": True,
    }
    assert got["steps"][2]["attribute"] == "well"


def test_set_workflow_unknown_task_is_400(client):
    res = client.post(
        "/api/workflow",
        json={"steps": [{"kind": "task", "task_name": "Nope [x]"}]},
    )
    assert res.status_code == 400


def test_run_without_steps_is_400(client):
    client.post("/api/workflow", json={"steps": []})
    assert client.post("/api/workflow/run", json={}).status_code == 400


def test_run_without_project_is_400(tmp_path):
    state.set_project(None)
    with TestClient(app) as c:
        assert c.post("/api/workflow/run", json={}).status_code == 400


def test_steps_to_workflow_builds_tasks_and_filters(seeded_client):
    uid = seeded_client.get("/api/tasks").json()[0]["unique_id"]
    payload = WorkflowPayload(
        name="wf",
        steps=[
            WorkflowStep(kind="task", task_name=uid, kwargs_parallel={"a": 1}),
            WorkflowStep(
                kind="filter", filter_type="attribute", attribute="w", value="A01"
            ),
            WorkflowStep(kind="filter", filter_type="type", key="is_3D", value=False),
        ],
    )
    wf = steps_to_workflow(payload)
    assert isinstance(wf.task_list[0], Task)
    assert wf.task_list[0].kwargs_parallel == {"a": 1}
    assert isinstance(wf.task_list[1], AttributeFilter)
    assert wf.task_list[1].value == "A01"
    assert isinstance(wf.task_list[2], TypeFilter)
    assert wf.task_list[2].value is False

    # And back to the payload shape.
    out = workflow_to_payload(wf)
    assert out["steps"][0]["task_name"] == uid
    assert out["steps"][2] == {
        "kind": "filter",
        "filter_type": "type",
        "key": "is_3D",
        "value": False,
    }


def test_save_load_round_trip(seeded_client, tmp_path):
    uid = seeded_client.get("/api/tasks").json()[0]["unique_id"]
    seeded_client.post(
        "/api/workflow",
        json={
            "name": "Saved",
            "steps": [
                {"kind": "task", "task_name": uid},
                {
                    "kind": "filter",
                    "filter_type": "type",
                    "key": "is_3D",
                    "value": True,
                },
            ],
        },
    )
    path = str(tmp_path / "wf.json")
    saved = seeded_client.post("/api/workflow/save", json={"path": path})
    assert saved.status_code == 200

    # Clobber, then load back.
    seeded_client.post("/api/workflow", json={"steps": []})
    loaded = seeded_client.post("/api/workflow/load", json={"path": path}).json()
    assert loaded["name"] == "Saved"
    assert [s["kind"] for s in loaded["steps"]] == ["task", "filter"]
    assert loaded["steps"][0]["task_name"] == uid


def test_workflow_run_streams_over_websocket(seeded_client, monkeypatch):
    from backend.routes import workflow as workflow_route
    from fractal_lite import RunResult

    def fake_run_workflow(project, start, end, **kw):
        on_output = kw.get("on_output")
        on_output("step 0")
        on_output("step 1")
        return RunResult(
            "completed", "2 step(s)", ["step 0", "step 1"], total_seconds=2.0
        )

    monkeypatch.setattr(workflow_route, "run_workflow", fake_run_workflow)

    uid = seeded_client.get("/api/tasks").json()[0]["unique_id"]
    seeded_client.post(
        "/api/workflow", json={"steps": [{"kind": "task", "task_name": uid}]}
    )

    job_id = seeded_client.post("/api/workflow/run", json={}).json()["job_id"]
    messages = []
    with seeded_client.websocket_connect(f"/api/run/{job_id}/ws") as ws:
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] in ("done", "error"):
                break

    assert [m["type"] for m in messages] == ["log", "log", "done"]
    assert messages[-1]["status"] == "completed"
    assert messages[-1]["summary"] == "2 step(s)"


def test_workflow_run_records_history(client):
    """A real run (a filter-only workflow, no subprocess) appends a restorable
    record served by ``GET /api/workflow/history`` (with the workflow snapshot
    converted to the frontend payload shape)."""
    from fractal_lite import Dataset, ZarrUrl, run_workflow

    project = state.get_project()
    project.dataset = Dataset(
        name="demo",
        zarr_dir="/tmp/z",
        zarr_urls=[ZarrUrl(url="/tmp/z/a", attributes={"well": "A01"})],
    )
    project.workflow = steps_to_workflow(
        WorkflowPayload(
            name="HistWF",
            steps=[
                WorkflowStep(
                    kind="filter",
                    filter_type="attribute",
                    attribute="well",
                    value="A01",
                )
            ],
        )
    )
    result = run_workflow(project)
    assert result.status == "completed"

    hist = client.get("/api/workflow/history").json()
    assert hist[-1]["name"] == "HistWF"
    assert hist[-1]["status"] == "completed"
    assert hist[-1]["payload"]["steps"][0]["filter_type"] == "attribute"


def test_project_persists_workflow(seeded_client):
    uid = seeded_client.get("/api/tasks").json()[0]["unique_id"]
    seeded_client.post(
        "/api/workflow",
        json={"name": "InSession", "steps": [{"kind": "task", "task_name": uid}]},
    )
    project_dir = str(state.get_project().project_dir)
    seeded_client.post("/api/project/save")

    # Drop the open project, then re-open it from disk; the workflow round-trips.
    state.set_project(None)
    opened = seeded_client.post(
        "/api/project/open", json={"project_dir": project_dir}
    )
    assert opened.status_code == 200
    assert seeded_client.get("/api/workflow").json()["name"] == "InSession"
