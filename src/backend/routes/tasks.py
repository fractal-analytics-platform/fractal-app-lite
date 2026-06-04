"""Task registry endpoints: list tasks, fetch schemas/details, collect, save/load."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.schemas import (
    CollectRequest,
    PackageIndexEntry,
    TaskDetails,
    TaskSchemaResponse,
    TaskSummary,
)
from fractal_lite import tasks_registry
from fractal_lite._package_index import load_package_index

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class RegistryPathRequest(BaseModel):
    path: str


def _summary(task) -> TaskSummary:
    inner = task.task
    return TaskSummary(
        name=inner.name,
        unique_id=task.unique_id,
        package=task.package_id,
        type=inner.type,
        category=inner.category,
        modality=inner.modality,
        tags=inner.tags,
        source=task.source,
        has_non_parallel=getattr(inner, "args_schema_non_parallel", None) is not None,
        has_parallel=getattr(inner, "args_schema_parallel", None) is not None,
    )


@router.get("", response_model=list[TaskSummary])
def list_tasks() -> list[TaskSummary]:
    """List every registered task with the phases it exposes a schema for."""
    return [_summary(t) for t in tasks_registry.tasks]


@router.get("/package-index", response_model=list[PackageIndexEntry])
def package_index() -> list[PackageIndexEntry]:
    """Curated GitHub-release task packages for the collect dropdown."""
    return [
        PackageIndexEntry(
            name=e.pkg_name,
            repo_url=e.repo_url,
            tag=e.tag,
            description=e.description,
        )
        for e in load_package_index()
    ]


@router.get("/{name}/schema", response_model=TaskSchemaResponse)
def task_schema(
    name: str,
    phase: str = Query("non_parallel", pattern="^(non_parallel|parallel)$"),
) -> TaskSchemaResponse:
    """Return the raw Pydantic-v2 JSON Schema for a task's arguments.

    This dict feeds the frontend ``JSchema`` component directly.
    """
    try:
        task = tasks_registry.get_task(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    attr = f"args_schema_{phase}"
    json_schema = getattr(task.task, attr, None)
    if json_schema is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task {name!r} has no {phase!r} argument schema.",
        )
    return TaskSchemaResponse(name=name, phase=phase, json_schema=json_schema)


@router.get("/{name}/details", response_model=TaskDetails)
def task_details(name: str) -> TaskDetails:
    """Return a task's docs + both raw argument schemas for the details panel."""
    try:
        task = tasks_registry.get_task(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    inner = task.task
    return TaskDetails(
        name=inner.name,
        unique_id=task.unique_id,
        package=task.package_id,
        type=inner.type,
        category=inner.category,
        modality=inner.modality,
        tags=inner.tags,
        source=task.source,
        docs_info=getattr(inner, "docs_info", None),
        args_schema_non_parallel=getattr(inner, "args_schema_non_parallel", None),
        args_schema_parallel=getattr(inner, "args_schema_parallel", None),
    )


@router.post("/collect", response_model=list[TaskSummary])
def collect(req: CollectRequest) -> list[TaskSummary]:
    """Register a task package from a local tarball/directory or a GitHub release."""
    if req.kind == "gitrelease":
        if not req.repo_url:
            raise HTTPException(
                status_code=400, detail="repo_url is required for kind 'gitrelease'."
            )
    else:
        if not req.path:
            raise HTTPException(
                status_code=400, detail=f"path is required for kind {req.kind!r}."
            )
        path = Path(req.path)
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"Path not found: {path}")
    try:
        if req.kind == "gitrelease":
            tasks_registry.collect_from_gitrelease(
                req.repo_url, req.tag or None, overwrite=req.overwrite
            )
        elif req.kind == "targz":
            tasks_registry.collect_from_targz(path, overwrite=req.overwrite)
        else:
            tasks_registry.collect_from_directory(path, overwrite=req.overwrite)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_summary(t) for t in tasks_registry.tasks]


@router.post("/registry/save")
def save_registry(req: RegistryPathRequest) -> dict:
    """Dump the whole task registry to a JSON file on disk."""
    try:
        tasks_registry.dump_to_json(req.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": req.path}


@router.post("/registry/load", response_model=list[TaskSummary])
def load_registry(req: RegistryPathRequest) -> list[TaskSummary]:
    """Load a registry from JSON, rebuilding its tasks from the stored sources."""
    if not Path(req.path).is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")
    try:
        # load_from_json re-collects from the sources itself.
        tasks_registry.load_from_json(req.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_summary(t) for t in tasks_registry.tasks]
