"""Native file-system dialog endpoints (open file / open dir / save file).

Each endpoint returns ``{"native": bool, "path": str | None}``. When ``native`` is
``False`` no OS dialog is available (browser / serve mode), so the frontend should
prompt for a typed path instead. When ``native`` is ``True``, ``path`` is the chosen
absolute path, or ``None`` if the user cancelled the dialog.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend import fs

router = APIRouter(prefix="/api/fs", tags=["fs"])


class OpenFileRequest(BaseModel):
    # pywebview file-type filters, e.g. ["CSV files (*.csv)", "All files (*.*)"].
    file_types: list[str] = ["All files (*.*)"]


class SaveFileRequest(BaseModel):
    default_name: str = ""
    file_types: list[str] = ["All files (*.*)"]


class DialogResponse(BaseModel):
    native: bool
    path: str | None = None


@router.post("/open-file", response_model=DialogResponse)
async def open_file(req: OpenFileRequest) -> DialogResponse:
    """Open a native 'pick a file' dialog."""
    if not fs.has_native_window():
        return DialogResponse(native=False)
    path = await run_in_threadpool(fs.open_file, tuple(req.file_types))
    return DialogResponse(native=True, path=path)


@router.post("/open-directory", response_model=DialogResponse)
async def open_directory() -> DialogResponse:
    """Open a native 'pick a folder' dialog."""
    if not fs.has_native_window():
        return DialogResponse(native=False)
    path = await run_in_threadpool(fs.open_directory)
    return DialogResponse(native=True, path=path)


@router.post("/save-file", response_model=DialogResponse)
async def save_file(req: SaveFileRequest) -> DialogResponse:
    """Open a native 'save as' dialog."""
    if not fs.has_native_window():
        return DialogResponse(native=False)
    path = await run_in_threadpool(
        fs.save_file, req.default_name, tuple(req.file_types)
    )
    return DialogResponse(native=True, path=path)
