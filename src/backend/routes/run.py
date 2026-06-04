"""Run endpoints: start a job, stream its log over a WebSocket, cancel it, get history.

``POST /api/run`` validates the request and launches the run on a daemon thread,
returning a ``job_id`` at once. The frontend then opens ``/api/run/{job_id}/ws`` to
receive each log line live and, last, a terminal ``done``/``error`` event carrying the
summary, metrics, and updated dataset. ``POST /api/run/{job_id}/cancel`` stops the run.
"""

import asyncio
import contextlib
import threading

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from backend.jobs import Job, job_manager
from backend.schemas import RunRequest
from backend.state import require_project
from fractal_lite import Project, run_task, tasks_registry

router = APIRouter(prefix="/api", tags=["run"])


def _worker(job: Job, project: Project, req: RunRequest) -> None:
    """Execute the run on a daemon thread, streaming output into the job's queue."""
    try:
        project.max_workers = req.max_workers
        result = run_task(
            project,
            req.task_name,
            req.kwargs_non_parallel,
            req.kwargs_parallel,
            req.filters,
            req.type_filters,
            on_output=job.emit,
            cancellation=job.cancellation,
        )
        # Persist the mutated project (dataset + sandbox history) to its directory.
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
        # The runner already recorded the failure in history; persist it, then surface
        # the error to the client as a terminal WS event.
        with contextlib.suppress(Exception):  # best-effort persistence
            project.save()
        job.finish({"type": "error", "detail": f"Run failed: {exc}"})


@router.post("/run")
async def start_run(
    req: RunRequest, project: Project = Depends(require_project)
) -> dict:
    """Validate, then launch a run on a worker thread; returns its ``job_id``."""
    try:
        tasks_registry.get_task(req.task_name)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    loop = asyncio.get_running_loop()
    job = job_manager.create(loop)
    threading.Thread(target=_worker, args=(job, project, req), daemon=True).start()
    return {"job_id": job.id}


@router.post("/run/{job_id}/cancel")
def cancel_run(job_id: str) -> dict:
    """Request cancellation of an in-flight run."""
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")
    job.cancellation.cancel()
    return {"job_id": job_id, "cancelling": True}


@router.websocket("/run/{job_id}/ws")
async def run_ws(websocket: WebSocket, job_id: str) -> None:
    """Stream a job's log lines, then its terminal event, then close."""
    await websocket.accept()
    job = job_manager.get(job_id)
    if job is None:
        await websocket.send_json({"type": "error", "detail": "No such job."})
        await websocket.close()
        return
    try:
        while True:
            msg = await job.queue.get()
            await websocket.send_json(msg)
            if msg["type"] in ("done", "error"):
                break
    except WebSocketDisconnect:
        # Client navigated away mid-run; the worker keeps going and folds results in.
        return
    finally:
        if job.done:
            job_manager.remove(job_id)
        await websocket.close()


@router.get("/run/history")
def run_history(project: Project = Depends(require_project)) -> list[dict]:
    """Return the sandbox run-history, newest last (matches in-memory order)."""
    return [rec.model_dump(mode="json") for rec in project.sandbox_history]
