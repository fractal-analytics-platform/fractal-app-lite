"""Project lifecycle endpoints: create, open, save, and read the current project.

A project is a directory holding one file per concern (``project.json``, ``table.csv``,
``workflow.json``, the two history files, ``registry.json``). Creating or opening one
replaces the process-wide open project; the frontend then refreshes the dataset,
workflow and histories from their own endpoints. There is no open project until one of
these endpoints is called.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.schemas import NewProjectRequest, OpenProjectRequest, ProjectInfo
from backend.state import get_project, require_project, set_project
from fractal_lite import Project

router = APIRouter(prefix="/api/project", tags=["project"])

_FLP = ".flp"


def _ensure_flp(path: Path) -> Path:
    return path if path.suffix == _FLP else path.with_name(path.name + _FLP)


def _info(project: Project) -> ProjectInfo:
    return ProjectInfo(
        project_dir=str(project.project_dir),
        name=project.name,
        description=project.description,
        zarr_dir=project.zarr_dir,
        max_workers=project.max_workers,
    )


@router.get("", response_model=ProjectInfo | None)
def current_project() -> ProjectInfo | None:
    """Return the currently open project's metadata, or ``None``."""
    project = get_project()
    return _info(project) if project is not None else None


@router.post("/new", response_model=ProjectInfo)
def new_project(req: NewProjectRequest) -> ProjectInfo:
    """Create a new project directory and open it.

    The project directory may already exist as long as it is empty. ``zarr_dir`` is
    created on disk so tasks have somewhere to write; when blank it defaults to a
    ``zarr_dir`` folder inside the project directory.
    """
    project_path = _ensure_flp(Path(req.project_dir))
    if project_path.exists():
        if not project_path.is_dir():
            raise HTTPException(
                status_code=400, detail=f"Not a directory: {req.project_dir}"
            )
        if any(project_path.iterdir()):
            raise HTTPException(
                status_code=400,
                detail=f"Project directory is not empty: {req.project_dir}",
            )
    zarr_dir = req.zarr_dir.strip() or str(project_path / "zarr_dir")
    try:
        Path(zarr_dir).mkdir(parents=True, exist_ok=True)
        project = Project.create(
            project_path,
            name=req.name,
            zarr_dir=zarr_dir,
            description=req.description,
            max_workers=req.max_workers,
            exist_ok=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_project(project)
    return _info(project)


@router.post("/open", response_model=ProjectInfo)
def open_project(req: OpenProjectRequest) -> ProjectInfo:
    """Open an existing project directory (best-effort registry re-collection)."""
    if not Path(req.project_dir).is_dir():
        raise HTTPException(
            status_code=400, detail=f"Project directory not found: {req.project_dir}"
        )
    if Path(req.project_dir).suffix != _FLP:
        logging.getLogger(__name__).warning(
            "Opening non-.flp project '%s' — consider renaming to '%s%s'.",
            req.project_dir,
            req.project_dir,
            _FLP,
        )
    try:
        project = Project.load(req.project_dir)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    set_project(project)
    return _info(project)


@router.post("/save", response_model=ProjectInfo)
def save_project(project: Project = Depends(require_project)) -> ProjectInfo:
    """Persist every artifact of the open project to its directory."""
    project.save()
    return _info(project)
