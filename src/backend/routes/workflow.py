"""Workflow endpoints: edit the current workflow, run it (whole or partial), and
save/load/import/export it.

The frontend edits a step list and syncs it here with ``POST /api/workflow``; ``GET``
pulls it back (used after a load/import rebuilds the canonical workflow). Running
mirrors ``routes/run.py`` and reuses the shared job machinery, so a workflow run streams
over the same ``/api/run/{job_id}/ws`` WebSocket and is cancelled via
``/api/run/{job_id}/cancel``.
"""

import asyncio
import contextlib
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend import workflow_service
from backend.jobs import Job, job_manager
from backend.schemas import WorkflowPayload, WorkflowRunRequest
from backend.state import require_project
from fractal_lite import Project, Workflow, run_workflow

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


@router.get("")
def get_workflow(project: Project = Depends(require_project)) -> dict:
    """Return the current workflow as the frontend step-list shape."""
    return workflow_service.workflow_to_payload(project.workflow)


@router.post("")
def set_workflow(
    payload: WorkflowPayload, project: Project = Depends(require_project)
) -> dict:
    """Replace the current workflow with the frontend's step list."""
    try:
        project.workflow = workflow_service.steps_to_workflow(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    project.save_workflow()
    return workflow_service.workflow_to_payload(project.workflow)


def _worker(job: Job, project: Project, req: WorkflowRunRequest) -> None:
    """Execute the workflow run on a daemon thread, streaming into the job's queue."""
    try:
        project.max_workers = req.max_workers
        result = run_workflow(
            project,
            req.start_task,
            req.end_task,
            on_output=job.emit,
            cancellation=job.cancellation,
        )
        project.save()
        job.finish(
            {
                "type": "done",
                "status": result.status,
                "summary": result.summary,
                "total_seconds": result.total_seconds,
                "mean_item_seconds": result.mean_item_seconds,
                "dataset": project.dataset.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        with contextlib.suppress(Exception):  # best-effort persistence
            project.save()
        job.finish({"type": "error", "detail": f"Workflow run failed: {exc}"})


@router.post("/run")
async def start_workflow_run(
    req: WorkflowRunRequest, project: Project = Depends(require_project)
) -> dict:
    """Validate, then launch a workflow run on a worker thread; returns its ``job_id``.

    The run streams over ``/api/run/{job_id}/ws`` and is cancellable via
    ``/api/run/{job_id}/cancel`` (shared job machinery).
    """
    if not project.workflow.task_list:
        raise HTTPException(status_code=400, detail="The workflow has no steps.")

    loop = asyncio.get_running_loop()
    job = job_manager.create(loop)
    threading.Thread(target=_worker, args=(job, project, req), daemon=True).start()
    return {"job_id": job.id}


@router.get("/history")
def workflow_history(project: Project = Depends(require_project)) -> list[dict]:
    """Return the workflow run-history, newest last (matches in-memory order).

    Each record's canonical ``Workflow`` snapshot is converted to the frontend's
    step-list ``payload`` shape so the editor can restore it.
    """
    return [
        {
            **rec.model_dump(mode="json", exclude={"workflow"}),
            "payload": (
                workflow_service.workflow_to_payload(rec.workflow)
                if rec.workflow is not None
                else None
            ),
        }
        for rec in project.workflow_history
    ]


@router.post("/save")
def save_workflow(payload: dict, project: Project = Depends(require_project)) -> dict:
    """Write the current workflow to ``payload['path']`` as lossless JSON."""
    path = payload.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="Missing 'path'.")
    Path(path).write_text(project.workflow.to_json())
    return {"path": path}


@router.post("/load")
def load_workflow(payload: dict, project: Project = Depends(require_project)) -> dict:
    """Restore the workflow from a lossless-JSON file; returns the step list."""
    path = payload.get("path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        project.workflow = Workflow.from_json(Path(path).read_text())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project.save_workflow()
    return workflow_service.workflow_to_payload(project.workflow)


@router.post("/export-fractal")
def export_workflow_fractal(
    payload: dict, project: Project = Depends(require_project)
) -> dict:
    """Write the workflow in Fractal's export format (lossy: filters are dropped)."""
    path = payload.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="Missing 'path'.")
    Path(path).write_text(project.workflow.to_fractal_json())
    return {"path": path}


@router.post("/import-fractal")
def import_workflow_fractal(
    payload: dict, project: Project = Depends(require_project)
) -> dict:
    """Import a Fractal workflow-export file; returns the step list.

    Tasks are resolved against the registry, auto-collecting from the package index when
    missing — so this can be slow and may hit the network.
    """
    path = payload.get("path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        project.workflow = Workflow.from_fractal_json(Path(path).read_text())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project.save_workflow()
    return workflow_service.workflow_to_payload(project.workflow)
