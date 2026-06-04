"""Pydantic request/response models for the REST API.

These are the transport contract between the Svelte frontend and the backend. They
are deliberately thin wrappers around the core types: the heavy domain models
(``Dataset``, ``Task``) are serialized via their own ``model_dump`` and embedded as
opaque JSON where needed.
"""

from typing import Any, Literal

from pydantic import BaseModel


class TaskSummary(BaseModel):
    """One row in the task list (GET /api/tasks)."""

    name: str
    # Stable identity used for lookups/runs: "{name} [{package}]".
    unique_id: str
    package: str
    type: str
    category: str | None = None
    modality: str | None = None
    tags: list[str] = []
    # Where the package was registered from (path or repo url).
    source: str = ""
    # Which argument phases this task exposes a schema for.
    has_non_parallel: bool = False
    has_parallel: bool = False


class TaskDetails(BaseModel):
    """A task's docs + raw argument schemas (GET /api/tasks/{name}/details)."""

    name: str
    unique_id: str
    package: str
    type: str
    category: str | None = None
    modality: str | None = None
    tags: list[str] = []
    source: str = ""
    docs_info: str | None = None
    args_schema_non_parallel: dict[str, Any] | None = None
    args_schema_parallel: dict[str, Any] | None = None


class TaskSchemaResponse(BaseModel):
    """Raw JSON Schema for a task's arguments (GET /api/tasks/{name}/schema)."""

    name: str
    phase: Literal["non_parallel", "parallel"]
    schema_version: Literal["pydantic_v2"] = "pydantic_v2"
    # The raw Pydantic-v2 JSON Schema dict straight from the task manifest.
    json_schema: dict[str, Any]


class CollectRequest(BaseModel):
    """Register a task package (POST /api/tasks/collect).

    ``path`` is required for the ``targz``/``directory`` kinds; ``repo_url`` (and
    optional ``tag``) for the ``gitrelease`` kind.
    """

    kind: Literal["targz", "directory", "gitrelease"]
    path: str | None = None
    repo_url: str | None = None
    tag: str | None = None
    overwrite: bool = True


class PackageIndexEntry(BaseModel):
    """One curated GitHub-release package (GET /api/tasks/package-index)."""

    name: str
    repo_url: str
    # Pinned release tag; empty/None means collect the latest release.
    tag: str | None = None
    description: str = ""


class RunRequest(BaseModel):
    """Submit an interactive single-task run (POST /api/run)."""

    task_name: str
    kwargs_non_parallel: dict[str, Any] | None = None
    kwargs_parallel: dict[str, Any] | None = None
    # Transient per-run filters as (attribute, value) pairs.
    filters: list[tuple[str, str]] = []
    # Transient per-run type filters as (key, value) boolean pairs.
    type_filters: list[tuple[str, bool]] = []
    max_workers: int = 1


class RunResponse(BaseModel):
    """Result of an interactive run."""

    status: Literal["completed", "cancelled", "failed"]
    summary: str
    # Captured subprocess + status log lines (Phase 5 moves these to a WebSocket).
    log: list[str] = []
    # The updated shared dataset (model_dump json), or None if unchanged/absent.
    dataset: dict[str, Any] | None = None


class WorkflowStep(BaseModel):
    """One step in a workflow (part of WorkflowPayload).

    A ``task`` step references a registered task by its ``task_name`` (``unique_id``)
    and carries its pre-filled kwargs. A ``filter`` step is an ``AttributeFilter``
    (``filter_type="attribute"``, uses ``attribute`` + string ``value``) or a
    ``TypeFilter`` (``filter_type="type"``, uses ``key`` + boolean ``value``).
    """

    kind: Literal["task", "filter"]
    # --- task step ---
    task_name: str | None = None
    kwargs_non_parallel: dict[str, Any] | None = None
    kwargs_parallel: dict[str, Any] | None = None
    # --- filter step ---
    filter_type: Literal["attribute", "type"] | None = None
    attribute: str | None = None
    key: str | None = None
    value: str | bool | None = None


class WorkflowPayload(BaseModel):
    """The editable workflow as exchanged with the frontend (GET/POST /api/workflow)."""

    name: str = "Unnamed Workflow"
    description: str | None = None
    steps: list[WorkflowStep] = []


class WorkflowRunRequest(BaseModel):
    """Run the current workflow, optionally a sub-range (POST /api/workflow/run)."""

    # Run steps [start_task, end_task); end_task=None runs to the end.
    start_task: int = 0
    end_task: int | None = None
    max_workers: int = 1


class SessionPayload(BaseModel):
    """The bundled session document (GET/POST /api/session)."""

    # Opaque pass-through of session_to_dict / apply_session_dict.
    data: dict[str, Any]
