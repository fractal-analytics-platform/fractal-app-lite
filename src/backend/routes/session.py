"""Session endpoints: get/set the bundled session document, and file load/save.

These reuse the existing JSON (de)serialization (``backend.session``) verbatim — the
on-disk shape is identical to the NiceGUI app's, so saved sessions keep loading.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend import session as session_io
from backend.schemas import SessionPayload
from backend.state import AppState, get_state

router = APIRouter(prefix="/api/session", tags=["session"])


@router.get("", response_model=SessionPayload)
def get_session(state: AppState = Depends(get_state)) -> SessionPayload:
    """Return the current session as a bundled document."""
    return SessionPayload(data=session_io.session_to_dict(state))


@router.post("", response_model=SessionPayload)
def set_session(
    payload: SessionPayload, state: AppState = Depends(get_state)
) -> SessionPayload:
    """Restore the session from a bundled document."""
    try:
        session_io.apply_session_dict(payload.data, state)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SessionPayload(data=session_io.session_to_dict(state))


@router.post("/save")
def save_to_file(payload: dict, state: AppState = Depends(get_state)) -> dict:
    """Write the current session to ``payload['path']`` as a bundled state.json."""
    path = payload.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="Missing 'path'.")
    session_io.save_session(path, state)
    return {"path": path}


@router.post("/load", response_model=SessionPayload)
def load_from_file(
    payload: dict, state: AppState = Depends(get_state)
) -> SessionPayload:
    """Restore the session from a state.json on disk."""
    path = payload.get("path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        session_io.load_session(path, state)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # ``load_session`` rehydrates the registry from the bundle's sources (and
    # re-resolves the workflow) best-effort, so no extra re-collection here.
    return SessionPayload(data=session_io.session_to_dict(state))
