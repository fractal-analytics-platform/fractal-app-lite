"""In-process registry of running task jobs, for live log streaming + cancellation.

A run is started by ``POST /api/run`` (returns a ``job_id``), executed on a daemon
thread, and observed over a WebSocket (``/api/run/{job_id}/ws``). The runner's
``on_output`` seam pushes each log line onto the job's ``asyncio.Queue`` from the worker
thread via ``loop.call_soon_threadsafe`` — so the event loop is never blocked and the WS
streams lines as they appear. A ``Cancellation`` token wired to the same run lets
``POST /api/run/{job_id}/cancel`` stop an in-flight run.

Single-user desktop app: one active run at a time is the norm, but the registry holds
multiple by id and is cleaned up when a WS finishes draining a job.
"""

import asyncio
import uuid
from typing import Any

from fractal_lite import Cancellation


class Job:
    """One run: its cancel token, its output queue, and its terminal payload."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.id = uuid.uuid4().hex
        self._loop = loop
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.cancellation = Cancellation()
        self.done = False

    def emit(self, line: str) -> None:
        """Push a log line (called from the worker thread)."""
        self._loop.call_soon_threadsafe(
            self.queue.put_nowait, {"type": "log", "line": line}
        )

    def finish(self, payload: dict[str, Any]) -> None:
        """Push the terminal event (done / error) from the worker thread."""
        self.done = True
        self._loop.call_soon_threadsafe(self.queue.put_nowait, payload)


class JobManager:
    """Process-wide registry of active jobs, keyed by id."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, loop: asyncio.AbstractEventLoop) -> Job:
        job = Job(loop)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def remove(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)


# Module-level singleton for the single-user process.
job_manager = JobManager()
