"""Minimal sandbox for running fractal tasks."""

from fractal_lite._dataset import Dataset, ZarrUrl
from fractal_lite._execution import Cancellation, RunCancelled, RunMetrics
from fractal_lite._package_index import PackageIndexEntry
from fractal_lite._registry import tasks_registry
from fractal_lite._tasks import ConverterCompoundTask, ParallelTask, Task
from fractal_lite._workflow import Workflow

__all__ = [
    "Cancellation",
    "ConverterCompoundTask",
    "Dataset",
    "PackageIndexEntry",
    "ParallelTask",
    "RunCancelled",
    "RunMetrics",
    "Task",
    "Workflow",
    "ZarrUrl",
    "tasks_registry",
]
