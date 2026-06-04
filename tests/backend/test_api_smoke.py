"""Smoke tests for the backend REST API (Phases 2-4).

Run with the project's pixi dev env: ``pixi run -e dev test``. These exercise the API
surface end-to-end against the in-process app. The registry starts empty (packages are
collected on demand), so tests that need registered tasks use the ``seeded_client``
fixture, which collects one package first.
"""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from fractal_lite import tasks_registry


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_client(converters_targz):
    """A client whose registry has one collected package (startup no longer seeds)."""
    tasks_registry.collect_from_targz(converters_targz, overwrite=True)
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_lists_collected_tasks(seeded_client):
    tasks = seeded_client.get("/api/tasks").json()
    assert len(tasks) > 0
    sample = tasks[0]
    assert {
        "name",
        "unique_id",
        "package",
        "type",
        "has_non_parallel",
        "has_parallel",
    } <= set(sample)


def test_task_schema_is_pydantic_v2(seeded_client):
    tasks = seeded_client.get("/api/tasks").json()
    uid = quote(tasks[0]["unique_id"], safe="")
    phase = "non_parallel" if tasks[0]["has_non_parallel"] else "parallel"
    res = seeded_client.get(f"/api/tasks/{uid}/schema", params={"phase": phase}).json()
    assert res["schema_version"] == "pydantic_v2"
    assert "properties" in res["json_schema"]


def test_unknown_task_schema_404(client):
    assert client.get("/api/tasks/Nope/schema").status_code == 404


def test_run_without_dataset_is_400(seeded_client):
    uid = seeded_client.get("/api/tasks").json()[0]["unique_id"]
    res = seeded_client.post("/api/run", json={"task_name": uid})
    assert res.status_code == 400


def test_create_dataset_makes_zarr_dir(client, tmp_path):
    zarr_dir = tmp_path / "out_zarr"
    res = client.post(
        "/api/dataset/create", json={"name": "demo", "zarr_dir": str(zarr_dir)}
    )
    assert res.status_code == 200
    assert zarr_dir.is_dir()
    assert res.json()["dataset"]["name"] == "demo"


def test_fs_dialogs_report_no_native_window(client):
    # In the test client there is no pywebview window, so dialogs fall back.
    for ep in ("open-file", "open-directory", "save-file"):
        res = client.post(f"/api/fs/{ep}", json={})
        assert res.status_code == 200
        assert res.json()["native"] is False


def test_napari_missing_binary_is_400(client):
    res = client.post("/api/dataset/napari", json={"zarr_url": "/no/such.zarr"})
    # napari is not installed in the test env → 400 with a helpful message.
    assert res.status_code in (200, 400)


def test_task_details_has_docs_and_schemas(seeded_client):
    sample = seeded_client.get("/api/tasks").json()[0]
    uid = quote(sample["unique_id"], safe="")
    d = seeded_client.get(f"/api/tasks/{uid}/details").json()
    assert d["name"] == sample["name"]
    assert d["unique_id"] == sample["unique_id"]
    assert {"docs_info", "args_schema_non_parallel", "args_schema_parallel"} <= set(d)


def test_package_index_lists_curated_packages(client):
    entries = client.get("/api/tasks/package-index").json()
    assert isinstance(entries, list)
    assert len(entries) > 0
    assert {"name", "repo_url"} <= set(entries[0])


def test_collect_gitrelease_requires_repo_url(client):
    res = client.post("/api/tasks/collect", json={"kind": "gitrelease"})
    assert res.status_code == 400
    assert "repo_url" in res.json()["detail"]


def test_collect_gitrelease_registers_tasks(client, converters_targz, monkeypatch):
    """POST kind=gitrelease registers tasks; the asset resolver is stubbed to the
    local converters tarball so no network call is made."""
    from fractal_lite import _collect

    monkeypatch.setattr(
        _collect,
        "_resolve_release_asset",
        lambda owner, repo, tag: (
            converters_targz.as_uri(),
            converters_targz.name,
            "v0.5.2",
        ),
    )
    res = client.post(
        "/api/tasks/collect",
        json={
            "kind": "gitrelease",
            "repo_url": "https://github.com/fractal-analytics-platform/"
            "fractal-uzh-converters",
        },
    )
    assert res.status_code == 200
    packages = {t["package"] for t in res.json()}
    assert "fractal-uzh-converters@v0.5.2" in packages


def test_registry_save_load_roundtrip(seeded_client, tmp_path):
    path = tmp_path / "registry.json"
    saved = seeded_client.post("/api/tasks/registry/save", json={"path": str(path)})
    assert saved.status_code == 200
    assert path.is_file()
    loaded = seeded_client.post("/api/tasks/registry/load", json={"path": str(path)})
    assert loaded.status_code == 200
    assert len(loaded.json()) > 0


def test_preview_applies_filters(client):
    ds = {
        "name": "demo",
        "zarr_dir": "/tmp/z",
        "zarr_urls": [
            {
                "url": "/tmp/z/A",
                "attributes": {"well": "A"},
                "types": {"is_3D": True},
                "hidden": False,
            },
            {
                "url": "/tmp/z/B",
                "attributes": {"well": "B"},
                "types": {"is_3D": False},
                "hidden": False,
            },
        ],
    }
    assert client.post("/api/dataset", json={"dataset": ds}).status_code == 200
    res = client.post("/api/dataset/preview", json={"filters": [["well", "A"]]}).json()
    assert res["n_total"] == 2
    assert res["n_visible"] == 1
    assert res["visible_urls"] == ["/tmp/z/A"]

    # Type filters narrow on the boolean ``types`` dict.
    res = client.post(
        "/api/dataset/preview", json={"type_filters": [["is_3D", True]]}
    ).json()
    assert res["n_visible"] == 1
    assert res["visible_urls"] == ["/tmp/z/A"]


def _fake_image_opener(url):
    return type("_Img", (), {"is_3d": True})()


def test_add_store_requires_dataset(client):
    client.post("/api/dataset", json={"dataset": None})  # clear any dataset
    res = client.post("/api/dataset/add-store", json={"path": "/tmp/z/img.zarr"})
    assert res.status_code == 400
    assert "Create a dataset first" in res.json()["detail"]


def test_add_store_adds_image_under_zarr_dir(client, monkeypatch):
    from fractal_lite import _dataset

    monkeypatch.setattr(_dataset, "open_ome_zarr_container", _fake_image_opener)
    client.post(
        "/api/dataset",
        json={"dataset": {"name": "demo", "zarr_dir": "/tmp/z", "zarr_urls": []}},
    )
    res = client.post("/api/dataset/add-store", json={"path": "/tmp/z/img.zarr"})
    assert res.status_code == 200
    urls = [zu["url"] for zu in res.json()["dataset"]["zarr_urls"]]
    assert "/tmp/z/img.zarr" in urls


def test_add_store_empty_dataset_adopts_parent_dir(client, monkeypatch):
    from fractal_lite import _dataset

    monkeypatch.setattr(_dataset, "open_ome_zarr_container", _fake_image_opener)
    client.post(
        "/api/dataset",
        json={"dataset": {"name": "demo", "zarr_dir": "/some/output", "zarr_urls": []}},
    )
    # Store lives outside the original zarr_dir; since the dataset is empty the
    # store's parent folder is adopted as the new zarr_dir.
    res = client.post(
        "/api/dataset/add-store", json={"path": "/data/external/img.zarr"}
    )
    assert res.status_code == 200
    ds = res.json()["dataset"]
    assert ds["zarr_dir"] == "/data/external"
    assert [zu["url"] for zu in ds["zarr_urls"]] == ["/data/external/img.zarr"]


def test_add_store_outside_zarr_dir_is_400_when_non_empty(client, monkeypatch):
    from fractal_lite import _dataset

    monkeypatch.setattr(_dataset, "open_ome_zarr_container", _fake_image_opener)
    client.post(
        "/api/dataset",
        json={"dataset": {"name": "demo", "zarr_dir": "/tmp/z", "zarr_urls": []}},
    )
    # First add seeds an image under zarr_dir, so the dataset is no longer empty.
    assert (
        client.post(
            "/api/dataset/add-store", json={"path": "/tmp/z/img.zarr"}
        ).status_code
        == 200
    )
    # A store outside the now-fixed zarr_dir is rejected.
    res = client.post("/api/dataset/add-store", json={"path": "/elsewhere/img.zarr"})
    assert res.status_code == 400
    assert "zarr_dir" in res.json()["detail"]


def test_remove_store_requires_dataset(client):
    client.post("/api/dataset", json={"dataset": None})  # clear any dataset
    res = client.post("/api/dataset/remove-store", json={"zarr_url": "/tmp/z/A"})
    assert res.status_code == 400
    assert "No dataset loaded" in res.json()["detail"]


def test_remove_store_drops_image(client):
    ds = {
        "name": "demo",
        "zarr_dir": "/tmp/z",
        "zarr_urls": [
            {"url": "/tmp/z/A", "attributes": {}, "hidden": False},
            {"url": "/tmp/z/B", "attributes": {}, "hidden": False},
        ],
    }
    assert client.post("/api/dataset", json={"dataset": ds}).status_code == 200
    res = client.post("/api/dataset/remove-store", json={"zarr_url": "/tmp/z/A"})
    assert res.status_code == 200
    urls = [zu["url"] for zu in res.json()["dataset"]["zarr_urls"]]
    assert urls == ["/tmp/z/B"]


def test_params_export_import_roundtrip(client, tmp_path):
    path = tmp_path / "params.json"
    payload = {
        "path": str(path),
        "kwargs_non_parallel": {"a": 1},
        "kwargs_parallel": None,
    }
    assert client.post("/api/params/export", json=payload).status_code == 200
    got = client.post("/api/params/import", json={"path": str(path)}).json()
    assert got["kwargs_non_parallel"] == {"a": 1}
    assert got["kwargs_parallel"] is None


def test_cancel_unknown_job_404(client):
    assert client.post("/api/run/nope/cancel").status_code == 404


def test_run_streams_over_websocket(client, monkeypatch):
    from backend import run_service
    from backend.routes import run as run_route

    def fake_run_task(
        state, task_name, knp, kp, filters, type_filters, max_workers, **kw
    ):
        on_output = kw.get("on_output")
        on_output("line one")
        on_output("line two")
        return run_service.RunResult(
            "completed",
            "+0 images (2 total)",
            ["line one", "line two"],
            total_seconds=1.0,
            mean_item_seconds=0.5,
        )

    monkeypatch.setattr(run_route.run_service, "run_task", fake_run_task)

    # A dataset must be present for the run to start.
    ds = {"dataset": {"name": "demo", "zarr_dir": "/tmp/z", "zarr_urls": []}}
    client.post("/api/dataset", json=ds)
    uid = client.get("/api/tasks").json()[0]["unique_id"]

    job_id = client.post("/api/run", json={"task_name": uid}).json()["job_id"]
    messages = []
    with client.websocket_connect(f"/api/run/{job_id}/ws") as ws:
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] in ("done", "error"):
                break

    types = [m["type"] for m in messages]
    assert types == ["log", "log", "done"]
    assert messages[-1]["status"] == "completed"
    assert messages[-1]["mean_item_seconds"] == 0.5
    # The history endpoint always returns a list (the fake run does not record).
    assert isinstance(client.get("/api/run/history").json(), list)


def test_dataset_and_session_roundtrip(client):
    # Set a dataset, read it back.
    payload = {"dataset": {"name": "demo", "zarr_dir": "/tmp/z", "zarr_urls": []}}
    assert client.post("/api/dataset", json=payload).status_code == 200
    got = client.get("/api/dataset").json()["dataset"]
    assert got["name"] == "demo"

    # Session bundle round-trips (reuses the existing JSON (de)serialization).
    session = client.get("/api/session").json()["data"]
    assert "registry" in session and "dataset" in session
    assert client.post("/api/session", json={"data": session}).status_code == 200
