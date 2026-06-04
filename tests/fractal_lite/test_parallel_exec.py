"""Tests for the concurrent parallel phase in ``_run_parallel_task``.

The heavy work happens in a ``pixi run`` subprocess via ``_run_executable``; we
monkeypatch that boundary so these tests exercise the pool orchestration
(concurrency, ordering, error aggregation, cancellation) without spawning pixi.
"""

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    import subprocess

from fractal_lite import _tasks as tasks_mod
from fractal_lite._tasks import (
    Cancellation,
    RunCancelled,
    RunMetrics,
    _run_parallel_task,
)

SRC = Path("/src")
PYPROJECT = Path("/src/pyproject.toml")


def _items(n: int) -> list[dict]:
    return [{"zarr_url": f"/z/{i}", "i": i} for i in range(n)]


def test_runs_concurrently_and_preserves_order(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_exec(kwargs, executable, source_location, pyproject_path, **_):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"i": kwargs["i"]}

    monkeypatch.setattr(tasks_mod, "_run_executable", fake_exec)

    results = _run_parallel_task(_items(8), "par.py", SRC, PYPROJECT, max_workers=4)

    # Output stays in input order regardless of completion order.
    assert [r["i"] for r in results if r is not None] == list(range(8))
    # Actually parallel, but capped at max_workers.
    assert peak > 1
    assert peak <= 4


def test_single_worker_is_sequential(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_exec(kwargs, executable, source_location, pyproject_path, **_):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"i": kwargs["i"]}

    monkeypatch.setattr(tasks_mod, "_run_executable", fake_exec)

    results = _run_parallel_task(_items(4), "par.py", SRC, PYPROJECT, max_workers=1)

    assert [r["i"] for r in results if r is not None] == [0, 1, 2, 3]
    assert peak == 1


def test_all_items_attempted_then_aggregated_error(monkeypatch):
    attempted: list[int] = []
    lock = threading.Lock()

    def fake_exec(kwargs, executable, source_location, pyproject_path, **_):
        with lock:
            attempted.append(kwargs["i"])
        if kwargs["i"] % 2 == 0:
            raise RuntimeError(f"boom {kwargs['i']}")
        return {"i": kwargs["i"]}

    monkeypatch.setattr(tasks_mod, "_run_executable", fake_exec)

    with pytest.raises(RuntimeError) as excinfo:
        _run_parallel_task(_items(5), "par.py", SRC, PYPROJECT, max_workers=3)

    # Every item ran despite failures (run-all-then-report).
    assert sorted(attempted) == [0, 1, 2, 3, 4]
    # Reports the failure count (items 0, 2, 4 failed).
    assert "3/5 parallel items failed" in str(excinfo.value)


def test_cancelled_before_start_raises_and_runs_nothing(monkeypatch):
    attempted: list[int] = []

    def fake_exec(kwargs, executable, source_location, pyproject_path, **_):
        attempted.append(kwargs["i"])
        return {"i": kwargs["i"]}

    monkeypatch.setattr(tasks_mod, "_run_executable", fake_exec)

    cancellation = Cancellation()
    cancellation.cancel()

    with pytest.raises(RunCancelled):
        _run_parallel_task(
            _items(4),
            "par.py",
            SRC,
            PYPROJECT,
            cancellation=cancellation,
            max_workers=2,
        )

    assert attempted == []


def test_metrics_record_measured_per_item_durations(monkeypatch):
    def fake_exec(kwargs, executable, source_location, pyproject_path, **_):
        time.sleep(0.05)
        return {"i": kwargs["i"]}

    monkeypatch.setattr(tasks_mod, "_run_executable", fake_exec)

    metrics = RunMetrics()
    _run_parallel_task(
        _items(4), "par.py", SRC, PYPROJECT, max_workers=4, metrics=metrics
    )

    assert len(metrics.item_durations) == 4
    assert all(d >= 0.04 for d in metrics.item_durations)
    # Measured mean reflects per-item time, not wall-clock/n (which would be ~0.05/4).
    mean = metrics.mean_item_seconds
    assert mean is not None
    assert mean >= 0.04


def test_metrics_record_even_when_item_fails(monkeypatch):
    def fake_exec(kwargs, executable, source_location, pyproject_path, **_):
        time.sleep(0.01)
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks_mod, "_run_executable", fake_exec)

    metrics = RunMetrics()
    with pytest.raises(RuntimeError):
        _run_parallel_task(
            _items(3), "par.py", SRC, PYPROJECT, max_workers=3, metrics=metrics
        )

    # A duration is recorded for every attempted item, including failures.
    assert len(metrics.item_durations) == 3


def test_metrics_mean_is_none_when_no_items_run():
    metrics = RunMetrics()
    assert metrics.mean_item_seconds is None


def test_cancel_terminates_all_registered_processes():
    class FakeProc:
        def __init__(self) -> None:
            self.terminated = False

        def poll(self):
            return None  # still running

        def terminate(self):
            self.terminated = True

    cancellation = Cancellation()
    procs = [FakeProc(), FakeProc(), FakeProc()]
    for p in procs:
        cancellation.register(cast("subprocess.Popen", p))

    cancellation.cancel()

    assert all(p.terminated for p in procs)
    assert cancellation.cancelled
