"""Workflow endpoints: edit the current workflow, run it (whole or partial), and
save/load/import/export it.

The frontend edits a step list and syncs it here with ``POST /api/workflow``; ``GET``
pulls it back (used after a load/import rebuilds the canonical workflow). Running
mirrors ``routes/run.py`` and reuses the shared job machinery, so a workflow run streams
over the same ``/api/run/{job_id}/ws`` WebSocket and is cancelled via
``/api/run/{job_id}/cancel``.
"""

import asyncio
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend import workflow_service
from backend.jobs import Job, job_manager
from backend.schemas import WorkflowPayload, WorkflowRunRequest
from backend.state import AppState, get_state
from fractal_lite import Workflow

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


@router.get("")
def get_workflow(state: AppState = Depends(get_state)) -> dict:
    """Return the current workflow as the frontend step-list shape."""
    return workflow_service.workflow_to_payload(state.workflow)


@router.post("")
def set_workflow(
    payload: WorkflowPayload, state: AppState = Depends(get_state)
) -> dict:
    """Replace the current workflow with the frontend's step list."""
    try:
        state.workflow = workflow_service.steps_to_workflow(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return workflow_service.workflow_to_payload(state.workflow)


def _worker(job: Job, state: AppState, req: WorkflowRunRequest) -> None:
    """Execute the workflow run on a daemon thread, streaming into the job's queue."""
    try:
        result = workflow_service.run_workflow(
            state,
            req.start_task,
            req.end_task,
            req.max_workers,
            on_output=job.emit,
            cancellation=job.cancellation,
        )
        job.finish(
            {
                "type": "done",
                "status": result.status,
                "summary": result.summary,
                "total_seconds": result.total_seconds,
                "mean_item_seconds": result.mean_item_seconds,
                "dataset": (
                    state.dataset.model_dump(mode="json") if state.dataset else None
                ),
            }
        )
    except Exception as exc:
        job.finish({"type": "error", "detail": f"Workflow run failed: {exc}"})


@router.post("/run")
async def start_workflow_run(
    req: WorkflowRunRequest, state: AppState = Depends(get_state)
) -> dict:
    """Validate, then launch a workflow run on a worker thread; returns its ``job_id``.

    The run streams over ``/api/run/{job_id}/ws`` and is cancellable via
    ``/api/run/{job_id}/cancel`` (shared job machinery).
    """
    if state.dataset is None:
        raise HTTPException(
            status_code=400, detail="No dataset loaded. Create or load a dataset first."
        )
    if not state.workflow.task_list:
        raise HTTPException(status_code=400, detail="The workflow has no steps.")

    loop = asyncio.get_running_loop()
    job = job_manager.create(loop)
    threading.Thread(target=_worker, args=(job, state, req), daemon=True).start()
    return {"job_id": job.id}


@router.get("/history")
def workflow_history(state: AppState = Depends(get_state)) -> list[dict]:
    """Return the workflow run-history, newest last (matches in-memory order)."""
    return [asdict(rec) for rec in state.workflow_history]


@router.post("/save")
def save_workflow(payload: dict, state: AppState = Depends(get_state)) -> dict:
    """Write the current workflow to ``payload['path']`` as lossless JSON."""
    path = payload.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="Missing 'path'.")
    Path(path).write_text(state.workflow.to_json())
    return {"path": path}


@router.post("/load")
def load_workflow(payload: dict, state: AppState = Depends(get_state)) -> dict:
    """Restore the workflow from a lossless-JSON file; returns the step list."""
    path = payload.get("path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        state.workflow = Workflow.from_json(Path(path).read_text())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workflow_service.workflow_to_payload(state.workflow)


@router.post("/export-fractal")
def export_workflow_fractal(
    payload: dict, state: AppState = Depends(get_state)
) -> dict:
    """Write the workflow in Fractal's export format (lossy: filters are dropped)."""
    path = payload.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="Missing 'path'.")
    Path(path).write_text(state.workflow.to_fractal_json())
    return {"path": path}


@router.post("/import-fractal")
def import_workflow_fractal(
    payload: dict, state: AppState = Depends(get_state)
) -> dict:
    """Import a Fractal workflow-export file; returns the step list.

    Tasks are resolved against the registry, auto-collecting from the package index when
    missing — so this can be slow and may hit the network.
    """
    path = payload.get("path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        state.workflow = Workflow.from_fractal_json(Path(path).read_text())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workflow_service.workflow_to_payload(state.workflow)
