"""Dataset endpoints: get/set the open project's dataset, CSV load/save, napari.

All mutations operate on the open project's ``dataset`` and are persisted to the
project directory (``table.csv``). Dataset *creation* is project creation — see
``routes/project.py`` (``POST /api/project/new``).
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.state import get_project, require_project
from fractal_lite import Dataset, Project
from fractal_lite._filters import AttributeFilter, TypeFilter

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


class DatasetPayload(BaseModel):
    """The open project's dataset as a model_dump dict, or None when no project."""

    dataset: dict[str, Any] | None = None


class PathPayload(BaseModel):
    path: str


class NapariRequest(BaseModel):
    zarr_url: str


class RemoveRequest(BaseModel):
    """Remove a single image from the dataset (POST /api/dataset/remove-store)."""

    zarr_url: str


class PreviewRequest(BaseModel):
    """Preview which images a run will touch (POST /api/dataset/preview)."""

    # Transient per-run filters as (attribute, value) pairs.
    filters: list[tuple[str, str]] = []
    # Transient per-run type filters as (key, value) boolean pairs.
    type_filters: list[tuple[str, bool]] = []
    # Optional selected task, so converter tasks get the right preview message.
    task_name: str | None = None


class PreviewResponse(BaseModel):
    is_converter: bool = False
    zarr_dir: str | None = None
    visible_urls: list[str] = []
    n_visible: int = 0
    n_total: int = 0


@router.get("", response_model=DatasetPayload)
def get_dataset() -> DatasetPayload:
    """Return the open project's dataset (or None when no project is open)."""
    project = get_project()
    return DatasetPayload(
        dataset=project.dataset.model_dump(mode="json") if project else None
    )


@router.post("", response_model=DatasetPayload)
def set_dataset(
    payload: DatasetPayload, project: Project = Depends(require_project)
) -> DatasetPayload:
    """Replace the open project's dataset from a model_dump dict."""
    if payload.dataset is None:
        raise HTTPException(
            status_code=400, detail="A project always has a dataset; cannot clear it."
        )
    try:
        project.dataset = Dataset.model_validate(payload.dataset)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project.save_dataset()
    return DatasetPayload(dataset=project.dataset.model_dump(mode="json"))


@router.post("/preview", response_model=PreviewResponse)
def preview(
    req: PreviewRequest, project: Project = Depends(require_project)
) -> PreviewResponse:
    """Apply the transient filters to a copy and report which images stay visible."""
    # Converter tasks ignore the existing image list — they run on zarr_dir.
    if req.task_name:
        try:
            inner = project.registry.get_task(req.task_name).task
            if inner.type.startswith("converter"):
                return PreviewResponse(
                    is_converter=True, zarr_dir=project.dataset.zarr_dir
                )
        except KeyError:
            pass

    working = project.dataset.model_copy(deep=True)
    for attr, val in req.filters:
        if attr:
            working = AttributeFilter(attribute=attr, value=val).run(working)
    for key, val in req.type_filters:
        if key:
            working = TypeFilter(key=key, value=val).run(working)
    visible = [zu.url for zu in working.zarr_urls if zu.active]
    return PreviewResponse(
        zarr_dir=project.dataset.zarr_dir,
        visible_urls=visible,
        n_visible=len(visible),
        n_total=len(project.dataset.zarr_urls),
    )


@router.post("/napari")
def open_in_napari(req: NapariRequest) -> dict:
    """Launch the installed napari CLI on a single image, detached."""
    try:
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(
            ["napari", req.zarr_url, "--plugin", "napari-ome-zarr"],
            **kwargs,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail="napari not found on PATH — install napari to use this.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"zarr_url": req.zarr_url}


@router.post("/load-csv", response_model=DatasetPayload)
def load_csv(
    payload: PathPayload, project: Project = Depends(require_project)
) -> DatasetPayload:
    """Load the dataset from a CSV file on disk (reuses Dataset.from_csv)."""
    path = Path(payload.path)
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        project.dataset = Dataset.from_csv(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project.save_dataset()
    return DatasetPayload(dataset=project.dataset.model_dump(mode="json"))


@router.post("/add-store", response_model=DatasetPayload)
def add_store(
    payload: PathPayload, project: Project = Depends(require_project)
) -> DatasetPayload:
    """Add an OME-Zarr store (image or plate) to the current dataset.

    Reuses ``Dataset.from_raw_urls``. All images in a dataset share a common
    ``zarr_dir``, so the store must live under it. When the dataset is still
    empty we adopt the picked store's parent folder as ``zarr_dir``, letting the
    user populate a dataset from existing data outside the original directory.
    """
    ds = project.dataset
    if not ds.zarr_urls:
        ds = ds.model_copy(update={"zarr_dir": str(Path(payload.path).parent)})
    try:
        project.dataset = ds.from_raw_urls([payload.path])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project.save_dataset()
    return DatasetPayload(dataset=project.dataset.model_dump(mode="json"))


@router.post("/remove-store", response_model=DatasetPayload)
def remove_store(
    req: RemoveRequest, project: Project = Depends(require_project)
) -> DatasetPayload:
    """Remove a single image (by exact ``zarr_url``) from the current dataset."""
    project.dataset = project.dataset.remove_zarr_url(req.zarr_url)
    project.save_dataset()
    return DatasetPayload(dataset=project.dataset.model_dump(mode="json"))


@router.post("/clear-images", response_model=DatasetPayload)
def clear_images(project: Project = Depends(require_project)) -> DatasetPayload:
    """Remove all images from the current dataset (keep the same zarr_dir)."""
    project.dataset = project.dataset.clear_images()
    project.save_dataset()
    return DatasetPayload(dataset=project.dataset.model_dump(mode="json"))


@router.post("/save-csv")
def save_csv(payload: PathPayload, project: Project = Depends(require_project)) -> dict:
    """Write the dataset to a CSV file on disk (reuses Dataset.to_csv)."""
    try:
        project.dataset.to_csv(payload.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": payload.path}
