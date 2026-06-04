"""Serializable run-history for the sandbox and the workflow.

Two record types (:class:`SandboxRunRecord` for single-task sandbox runs and
:class:`WorkflowRunRecord` for multi-step workflow runs) are held in one generic,
append-only :class:`History` container. The container assigns 1-based indices,
serializes to JSON, and truncates over-long summaries on the way out.

Ported from the backend's ``RunRecord``/``WorkflowRunRecord`` dataclasses
(``backend/state.py``); the records are now Pydantic models, and the workflow
snapshot is a real :class:`Workflow` (lossless) rather than a frontend-shaped dict.
"""

import json
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from fractal_lite._workflow import Workflow

# Cap embedded run/workflow summaries (failed runs can carry full tracebacks).
MAX_SUMMARY_CHARS = 4000


def _truncate_summary(summary: str) -> str:
    """Trim an over-long summary to a head+tail with an elision marker."""
    if not summary or len(summary) <= MAX_SUMMARY_CHARS:
        return summary
    head = MAX_SUMMARY_CHARS // 2
    tail = MAX_SUMMARY_CHARS - head
    omitted = len(summary) - MAX_SUMMARY_CHARS
    return f"{summary[:head]}\n... [{omitted} chars elided] ...\n{summary[-tail:]}"


class SandboxRunRecord(BaseModel):
    """One entry in the sandbox run-history (a single-task run)."""

    index: int = 0
    task_name: str
    # Attribute filters applied for this run, as (attribute, value) pairs.
    filters: list[tuple[str, str]] = Field(default_factory=list)
    # Type filters applied for this run, as (key, value) boolean pairs.
    type_filters: list[tuple[str, bool]] = Field(default_factory=list)
    kwargs_non_parallel: dict | None = None
    kwargs_parallel: dict | None = None
    # Human-readable result summary, e.g. "+8 images (42 total)".
    summary: str = ""
    # Outcome of the run: "completed", "cancelled", or "failed".
    status: str = "completed"


class WorkflowRunRecord(BaseModel):
    """One entry in the workflow run-history (a multi-step workflow run)."""

    index: int = 0
    name: str = ""
    # Human-readable result summary, e.g. "3 step(s): 8 → 42 images (42 visible)".
    summary: str = ""
    # Outcome of the run: "completed", "cancelled", or "failed".
    status: str = "completed"
    # Snapshot of the workflow as run, so a run can be fully restored into the
    # editor. Its task schemas are blanked on save and re-resolved on load.
    workflow: Workflow | None = None
    # The [start, end) sub-range that was actually run (display only).
    start_task: int = 0
    end_task: int | None = None


RecordT = TypeVar("RecordT", bound=WorkflowRunRecord | SandboxRunRecord)


class History(BaseModel, Generic[RecordT]):
    """Append-only, serializable list of run records.

    Parametrize with a record model to get a concrete history, e.g.
    ``History[SandboxRunRecord]`` (see :data:`SandboxHistory` /
    :data:`WorkflowHistory`).
    """

    records: list[RecordT] = Field(default_factory=list)

    def add(self, record: RecordT) -> RecordT:
        """Append ``record``, assigning it the next 1-based index. Returns it."""
        record.index = len(self.records) + 1
        self.records.append(record)
        return record

    def clear(self) -> None:
        """Drop all records."""
        self.records.clear()

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __getitem__(self, item):
        return self.records[item]

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize to JSON, truncating each record's ``summary`` field."""
        data = self.model_dump(mode="json")
        for record in data["records"]:
            if "summary" in record:
                record["summary"] = _truncate_summary(record["summary"])
        return json.dumps(data, indent=indent)

    @classmethod
    def from_json(cls, data: str) -> "History[RecordT]":
        """Reconstruct a history from :meth:`to_json` output."""
        return cls.model_validate_json(data)


# Concrete histories used by Project.
SandboxHistory = History[SandboxRunRecord]
WorkflowHistory = History[WorkflowRunRecord]
