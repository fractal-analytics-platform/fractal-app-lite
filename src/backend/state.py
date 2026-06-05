"""Shared, in-process application state for the sandbox v2 backend.

This is a single-user local desktop app, so a module-level singleton holding the
currently open :class:`~fractal_lite.Project` is sufficient. A ``Project`` owns the
dataset, the workflow, both run-histories, the project settings, and its own task
registry (``project.registry``), and persists itself to a project directory (one
file per concern). The registry is therefore per-project, not a global singleton.

The project is injected into FastAPI handlers via the ``require_project`` dependency
so handlers stay testable. There is no project until the user creates one
(``POST /api/project/new``) or opens one (``POST /api/project/open``).
"""

from fastapi import HTTPException

from fractal_lite import Project

# Module-level singleton for the single-user process. ``None`` until a project is
# created or opened.
_project: Project | None = None


def get_project() -> Project | None:
    """Return the currently open project, or ``None`` when none is open."""
    return _project


def set_project(project: Project | None) -> None:
    """Replace the process-wide open project (or clear it with ``None``)."""
    global _project
    _project = project


def require_project() -> Project:
    """FastAPI dependency returning the open project, 400-ing when there is none."""
    if _project is None:
        raise HTTPException(
            status_code=400, detail="No project open. Create or open a project first."
        )
    return _project
