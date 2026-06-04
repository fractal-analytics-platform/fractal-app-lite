"""Dataset endpoints: get/set the shared dataset, CSV load/save, create, napari."""

import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.state import AppState, get_state
from fractal_lite import Dataset, tasks_registry
from fractal_lite._filters import AttributeFilter, TypeFilter

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


class DatasetPayload(BaseModel):
    """The shared dataset as a model_dump dict, or None when absent."""

    dataset: dict[str, Any] | None = None


class PathPayload(BaseModel):
    path: str


class CreateRequest(BaseModel):
    """Create an empty dataset (POST /api/dataset/create)."""

    name: str = "dataset"
    zarr_dir: str


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
def get_dataset(state: AppState = Depends(get_state)) -> DatasetPayload:
    """Return the current shared dataset (or None)."""
    return DatasetPayload(
        dataset=state.dataset.model_dump(mode="json") if state.dataset else None
    )


@router.post("", response_model=DatasetPayload)
def set_dataset(
    payload: DatasetPayload, state: AppState = Depends(get_state)
) -> DatasetPayload:
    """Replace the shared dataset from a model_dump dict (or clear it with None)."""
    if payload.dataset is None:
        state.dataset = None
        return DatasetPayload(dataset=None)
    try:
        state.dataset = Dataset.model_validate(payload.dataset)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DatasetPayload(dataset=state.dataset.model_dump(mode="json"))


@router.post("/create", response_model=DatasetPayload)
def create_dataset(
    req: CreateRequest, state: AppState = Depends(get_state)
) -> DatasetPayload:
    """Create an empty dataset, making ``zarr_dir`` on disk so tasks can write to it."""
    try:
        Path(req.zarr_dir).mkdir(parents=True, exist_ok=True)
        state.dataset = Dataset(name=req.name, zarr_dir=req.zarr_dir, zarr_urls=[])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DatasetPayload(dataset=state.dataset.model_dump(mode="json"))


@router.post("/preview", response_model=PreviewResponse)
def preview(
    req: PreviewRequest, state: AppState = Depends(get_state)
) -> PreviewResponse:
    """Apply the transient filters to a copy and report which images stay visible."""
    if state.dataset is None:
        return PreviewResponse()

    # Converter tasks ignore the existing image list — they run on zarr_dir.
    if req.task_name:
        try:
            inner = tasks_registry.get_task(req.task_name).task
            if inner.type.startswith("converter"):
                return PreviewResponse(
                    is_converter=True, zarr_dir=state.dataset.zarr_dir
                )
        except KeyError:
            pass

    working = state.dataset.model_copy(deep=True)
    for attr, val in req.filters:
        if attr:
            working = AttributeFilter(attribute=attr, value=val).run(working)
    for key, val in req.type_filters:
        if key:
            working = TypeFilter(key=key, value=val).run(working)
    visible = [zu.url for zu in working.zarr_urls if zu.active]
    return PreviewResponse(
        zarr_dir=state.dataset.zarr_dir,
        visible_urls=visible,
        n_visible=len(visible),
        n_total=len(state.dataset.zarr_urls),
    )


@router.post("/napari")
def open_in_napari(req: NapariRequest) -> dict:
    """Launch the installed napari CLI on a single image, detached."""
    try:
        subprocess.Popen(
            ["napari", req.zarr_url, "--plugin", "napari-ome-zarr"],
            start_new_session=True,
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
    payload: PathPayload, state: AppState = Depends(get_state)
) -> DatasetPayload:
    """Load the shared dataset from a CSV file on disk (reuses Dataset.from_csv)."""
    path = Path(payload.path)
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        state.dataset = Dataset.from_csv(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DatasetPayload(dataset=state.dataset.model_dump(mode="json"))


@router.post("/add-store", response_model=DatasetPayload)
def add_store(
    payload: PathPayload, state: AppState = Depends(get_state)
) -> DatasetPayload:
    """Add an OME-Zarr store (image or plate) to the current dataset.

    Reuses ``Dataset.from_raw_urls``. All images in a dataset share a common
    ``zarr_dir``, so the store must live under it. When the dataset is still
    empty we adopt the picked store's parent folder as ``zarr_dir``, letting the
    user populate a dataset from existing data outside the original directory.
    """
    if state.dataset is None:
        raise HTTPException(status_code=400, detail="Create a dataset first.")
    ds = state.dataset
    if not ds.zarr_urls:
        ds = ds.model_copy(update={"zarr_dir": str(Path(payload.path).parent)})
    try:
        state.dataset = ds.from_raw_urls([payload.path])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DatasetPayload(dataset=state.dataset.model_dump(mode="json"))


@router.post("/remove-store", response_model=DatasetPayload)
def remove_store(
    req: RemoveRequest, state: AppState = Depends(get_state)
) -> DatasetPayload:
    """Remove a single image (by exact ``zarr_url``) from the current dataset."""
    if state.dataset is None:
        raise HTTPException(status_code=400, detail="No dataset loaded.")
    state.dataset = state.dataset.remove_zarr_url(req.zarr_url)
    return DatasetPayload(dataset=state.dataset.model_dump(mode="json"))


@router.post("/save-csv")
def save_csv(payload: PathPayload, state: AppState = Depends(get_state)) -> dict:
    """Write the shared dataset to a CSV file on disk (reuses Dataset.to_csv)."""
    if state.dataset is None:
        raise HTTPException(status_code=400, detail="No dataset to save.")
    try:
        state.dataset.to_csv(payload.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": payload.path}
