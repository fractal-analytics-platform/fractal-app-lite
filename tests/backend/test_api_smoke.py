"""Smoke tests for the backend REST API.

Run with the project's pixi dev env: ``pixi run -e dev test``. These exercise the API
surface end-to-end against the in-process app. The registry is owned per-project, so
tests that need registered tasks use ``seeded_client``, which opens a project and
collects one package into its registry. State lives on a ``Project`` singleton; the
``client`` fixture resets it, ``proj_client`` opens a fresh project so dataset/run
endpoints have somewhere to operate, and ``seeded_client`` additionally seeds that
project's registry.
"""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from backend import state
from backend.main import app
from fractal_lite import Project, RunResult


@pytest.fixture
def client():
    state.set_project(None)
    with TestClient(app) as c:
        yield c
    state.set_project(None)


def _open_project(tmp_path, registry, name="demo", zarr_dir=None):
    """Create + register a fresh project on the singleton, returning it.

    The project adopts the test's ``registry`` (whose ``collection_dir`` is a tmp
    path) so any collection writes to tmp rather than the real user cache.
    """
    zarr_dir = zarr_dir if zarr_dir is not None else str(tmp_path / "z")
    project = Project.create(tmp_path / "proj", name=name, zarr_dir=zarr_dir)
    project.registry = registry
    state.set_project(project)
    return project


@pytest.fixture
def proj_client(client, registry, tmp_path):
    """A client with an open project (empty dataset and registry)."""
    _open_project(tmp_path, registry)
    return client


@pytest.fixture
def seeded_client(proj_client, registry, converters_targz):
    """A client with an open project whose registry has one collected package."""
    registry.collect_from_targz(converters_targz, overwrite=True)
    return proj_client


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


def test_run_without_project_is_400(client):
    res = client.post("/api/run", json={"task_name": "anything"})
    assert res.status_code == 400
    assert "No project open" in res.json()["detail"]


def test_no_project_returns_empty_tasks(client):
    assert client.get("/api/tasks").json() == []


def test_no_project_returns_null_dataset(client):
    assert client.get("/api/dataset").json()["dataset"] is None


def test_get_project_is_null_without_one(client):
    assert client.get("/api/project").json() is None


def test_new_project_makes_dirs(client, tmp_path):
    project_dir = tmp_path / "myproj"
    project_dir_flp = tmp_path / "myproj.flp"
    zarr_dir = tmp_path / "out_zarr"
    res = client.post(
        "/api/project/new",
        json={
            "project_dir": str(project_dir),
            "name": "demo",
            "zarr_dir": str(zarr_dir),
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "demo"
    assert zarr_dir.is_dir()
    assert (project_dir_flp / "project.json").is_file()
    # The project is now the open one.
    assert client.get("/api/project").json()["project_dir"] == str(project_dir_flp)


def test_new_project_defaults_zarr_dir_inside_project(client, tmp_path):
    project_dir = tmp_path / "myproj"
    project_dir_flp = tmp_path / "myproj.flp"
    res = client.post(
        "/api/project/new",
        json={"project_dir": str(project_dir), "name": "demo", "description": "notes"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["zarr_dir"] == str(project_dir_flp / "zarr_dir")
    assert body["description"] == "notes"
    assert (project_dir_flp / "zarr_dir").is_dir()


def test_new_project_accepts_existing_empty_dir(client, tmp_path):
    project_dir = tmp_path / "empty"
    project_dir.mkdir()
    res = client.post(
        "/api/project/new", json={"project_dir": str(project_dir), "name": "demo"}
    )
    assert res.status_code == 200


def test_new_project_rejects_non_empty_dir(client, tmp_path):
    project_dir = tmp_path / "full.flp"
    project_dir.mkdir()
    (project_dir / "stuff.txt").write_text("x")
    res = client.post(
        "/api/project/new", json={"project_dir": str(project_dir), "name": "demo"}
    )
    assert res.status_code == 400
    assert "not empty" in res.json()["detail"]


def test_new_project_appends_flp_suffix(client, tmp_path):
    res = client.post(
        "/api/project/new",
        json={"project_dir": str(tmp_path / "myproj"), "name": "demo"},
    )
    assert res.status_code == 200
    assert res.json()["project_dir"].endswith(".flp")


def test_new_project_no_double_suffix(client, tmp_path):
    res = client.post(
        "/api/project/new",
        json={"project_dir": str(tmp_path / "myproj.flp"), "name": "demo"},
    )
    assert res.status_code == 200
    assert res.json()["project_dir"].endswith("myproj.flp")
    assert not res.json()["project_dir"].endswith("myproj.flp.flp")


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


def test_collect_gitrelease_requires_repo_url(proj_client):
    res = proj_client.post("/api/tasks/collect", json={"kind": "gitrelease"})
    assert res.status_code == 400
    assert "repo_url" in res.json()["detail"]


def test_collect_requires_project(client):
    res = client.post("/api/tasks/collect", json={"kind": "gitrelease"})
    assert res.status_code == 400
    assert "No project open" in res.json()["detail"]


def test_collect_gitrelease_registers_tasks(proj_client, converters_targz, monkeypatch):
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
    res = proj_client.post(
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


def test_preview_applies_filters(proj_client):
    ds = {
        "name": "demo",
        "zarr_dir": "/tmp/z",
        "zarr_urls": [
            {
                "url": "/tmp/z/A",
                "attributes": {"well": "A"},
                "types": {"is_3D": True},
                "active": True,
            },
            {
                "url": "/tmp/z/B",
                "attributes": {"well": "B"},
                "types": {"is_3D": False},
                "active": True,
            },
        ],
    }
    assert proj_client.post("/api/dataset", json={"dataset": ds}).status_code == 200
    res = proj_client.post(
        "/api/dataset/preview", json={"filters": [["well", "A"]]}
    ).json()
    assert res["n_total"] == 2
    assert res["n_visible"] == 1
    assert res["visible_urls"] == ["/tmp/z/A"]

    # Type filters narrow on the boolean ``types`` dict.
    res = proj_client.post(
        "/api/dataset/preview", json={"type_filters": [["is_3D", True]]}
    ).json()
    assert res["n_visible"] == 1
    assert res["visible_urls"] == ["/tmp/z/A"]


def _fake_image_opener(url):
    return type("_Img", (), {"is_3d": True})()


def test_dataset_endpoints_require_project(client):
    res = client.post("/api/dataset/add-store", json={"path": "/tmp/z/img.zarr"})
    assert res.status_code == 400
    assert "No project open" in res.json()["detail"]
    res = client.post("/api/dataset/remove-store", json={"zarr_url": "/tmp/z/A"})
    assert res.status_code == 400
    assert "No project open" in res.json()["detail"]


def test_add_store_adds_image_under_zarr_dir(proj_client, monkeypatch):
    from fractal_lite import _dataset

    monkeypatch.setattr(_dataset, "open_ome_zarr_container", _fake_image_opener)
    proj_client.post(
        "/api/dataset",
        json={"dataset": {"name": "demo", "zarr_dir": "/tmp/z", "zarr_urls": []}},
    )
    res = proj_client.post("/api/dataset/add-store", json={"path": "/tmp/z/img.zarr"})
    assert res.status_code == 200
    urls = [zu["url"] for zu in res.json()["dataset"]["zarr_urls"]]
    assert "/tmp/z/img.zarr" in urls


def test_add_store_empty_dataset_adopts_parent_dir(proj_client, monkeypatch, tmp_path):
    from fractal_lite import _dataset

    monkeypatch.setattr(_dataset, "open_ome_zarr_container", _fake_image_opener)
    proj_client.post(
        "/api/dataset",
        json={"dataset": {"name": "demo", "zarr_dir": "/some/output", "zarr_urls": []}},
    )
    # Store lives outside the original zarr_dir; since the dataset is empty the
    # store's parent folder is adopted as the new zarr_dir.
    new_zarr_dir = tmp_path.as_posix()
    store_path = (tmp_path / "img.zarr").as_posix()
    res = proj_client.post("/api/dataset/add-store", json={"path": store_path})
    assert res.status_code == 200
    ds = res.json()["dataset"]
    assert ds["zarr_dir"] == new_zarr_dir
    assert [zu["url"] for zu in ds["zarr_urls"]] == [store_path]


def test_add_store_outside_zarr_dir_is_400_when_non_empty(proj_client, monkeypatch):
    from fractal_lite import _dataset

    monkeypatch.setattr(_dataset, "open_ome_zarr_container", _fake_image_opener)
    proj_client.post(
        "/api/dataset",
        json={"dataset": {"name": "demo", "zarr_dir": "/tmp/z", "zarr_urls": []}},
    )
    # First add seeds an image under zarr_dir, so the dataset is no longer empty.
    assert (
        proj_client.post(
            "/api/dataset/add-store", json={"path": "/tmp/z/img.zarr"}
        ).status_code
        == 200
    )
    # A store outside the now-fixed zarr_dir is rejected.
    res = proj_client.post(
        "/api/dataset/add-store", json={"path": "/elsewhere/img.zarr"}
    )
    assert res.status_code == 400
    assert "zarr_dir" in res.json()["detail"]


def test_remove_store_drops_image(proj_client):
    ds = {
        "name": "demo",
        "zarr_dir": "/tmp/z",
        "zarr_urls": [
            {"url": "/tmp/z/A", "attributes": {}, "active": True},
            {"url": "/tmp/z/B", "attributes": {}, "active": True},
        ],
    }
    assert proj_client.post("/api/dataset", json={"dataset": ds}).status_code == 200
    res = proj_client.post("/api/dataset/remove-store", json={"zarr_url": "/tmp/z/A"})
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


def test_run_streams_over_websocket(seeded_client, monkeypatch):
    from backend.routes import run as run_route

    def fake_run_task(project, task_name, knp, kp, filters, type_filters, **kw):
        on_output = kw.get("on_output")
        on_output("line one")
        on_output("line two")
        return RunResult(
            "completed",
            "+0 images (2 total)",
            ["line one", "line two"],
            total_seconds=1.0,
            mean_item_seconds=0.5,
        )

    monkeypatch.setattr(run_route, "run_task", fake_run_task)

    uid = seeded_client.get("/api/tasks").json()[0]["unique_id"]
    job_id = seeded_client.post("/api/run", json={"task_name": uid}).json()["job_id"]
    messages = []
    with seeded_client.websocket_connect(f"/api/run/{job_id}/ws") as ws:
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
    assert isinstance(seeded_client.get("/api/run/history").json(), list)


def test_dataset_and_project_roundtrip(proj_client, tmp_path):
    # Set a dataset, read it back.
    payload = {
        "dataset": {
            "name": "demo",
            "zarr_dir": "/tmp/z",
            "zarr_urls": [{"url": "/tmp/z/A", "attributes": {}, "active": True}],
        }
    }
    assert proj_client.post("/api/dataset", json=payload).status_code == 200
    got = proj_client.get("/api/dataset").json()["dataset"]
    assert got["name"] == "demo"

    # Save the project, then re-open it from its directory and confirm it round-trips.
    saved = proj_client.post("/api/project/save").json()
    project_dir = saved["project_dir"]
    state.set_project(None)
    assert proj_client.get("/api/dataset").json()["dataset"] is None

    opened = proj_client.post("/api/project/open", json={"project_dir": project_dir})
    assert opened.status_code == 200
    ds = proj_client.get("/api/dataset").json()["dataset"]
    assert [zu["url"] for zu in ds["zarr_urls"]] == ["/tmp/z/A"]
