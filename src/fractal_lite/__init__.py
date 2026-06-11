"""Minimal sandbox for running fractal tasks."""

from fractal_lite.__version__ import __version__
from fractal_lite._dataset import Dataset, ZarrUrl
from fractal_lite._execution import Cancellation, RunCancelled, RunMetrics
from fractal_lite._history import (
    History,
    SandboxHistory,
    SandboxRunRecord,
    WorkflowHistory,
    WorkflowRunRecord,
)
from fractal_lite._package_index import PackageIndexEntry
from fractal_lite._project import Project, ProjectIndex
from fractal_lite._registry import TasksRegistry
from fractal_lite._runner import RunResult, run_task, run_workflow
from fractal_lite._tasks import ConverterCompoundTask, ParallelTask, Task
from fractal_lite._workflow import Workflow

__all__ = [
    "Cancellation",
    "ConverterCompoundTask",
    "Dataset",
    "History",
    "PackageIndexEntry",
    "ParallelTask",
    "Project",
    "ProjectIndex",
    "RunCancelled",
    "RunMetrics",
    "RunResult",
    "SandboxHistory",
    "SandboxRunRecord",
    "Task",
    "TasksRegistry",
    "Workflow",
    "WorkflowHistory",
    "WorkflowRunRecord",
    "ZarrUrl",
    "__version__",
    "run_task",
    "run_workflow",
]
