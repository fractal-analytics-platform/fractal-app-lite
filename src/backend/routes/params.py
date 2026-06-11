"""Export / import a task's parameters as a standalone JSON file on disk.

Mirrors the NiceGUI app's Export/Import params: the current init + parallel kwargs are
written to (or read from) a JSON file chosen via the native file dialog. The path is a
server-side filesystem path (same machine as this single-user desktop app).
"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend._write_text import write_dict_to_file

router = APIRouter(prefix="/api/params", tags=["params"])


class ExportRequest(BaseModel):
    path: str
    kwargs_non_parallel: dict[str, Any] | None = None
    kwargs_parallel: dict[str, Any] | None = None


class ParamsPayload(BaseModel):
    kwargs_non_parallel: dict[str, Any] | None = None
    kwargs_parallel: dict[str, Any] | None = None


class ImportRequest(BaseModel):
    path: str


@router.post("/export")
def export_params(req: ExportRequest) -> dict:
    """Write the given kwargs to ``req.path`` as an indented JSON document."""
    payload = {
        "kwargs_non_parallel": req.kwargs_non_parallel or None,
        "kwargs_parallel": req.kwargs_parallel or None,
    }
    try:
        write_dict_to_file(req.path, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": req.path}


@router.post("/import", response_model=ParamsPayload)
def import_params(req: ImportRequest) -> ParamsPayload:
    """Read kwargs back from a params JSON file on disk."""
    path = Path(req.path)
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ParamsPayload(
        kwargs_non_parallel=data.get("kwargs_non_parallel"),
        kwargs_parallel=data.get("kwargs_parallel"),
    )
