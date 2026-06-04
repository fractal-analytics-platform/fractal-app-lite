"""FastAPI application: API routers + static frontend, single process (brief's §2).

One process serves both the REST API (under ``/api``) and the built Svelte assets, so
there is no CORS and no second server. pywebview (``backend.shell``) points a native
window at this app.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.routes import dataset, fs, params, project, run, tasks, workflow

logger = logging.getLogger(__name__)

# The SvelteKit static build (adapter-static) lands here once the frontend is built.
_FRONTEND_BUILD = Path(__file__).resolve().parents[1] / "frontend" / "build"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """The registry starts empty; packages are collected on demand via the API."""
    logging.basicConfig(level=logging.INFO)
    yield


def create_app() -> FastAPI:
    """Build the FastAPI app: API routers first, then the static frontend last."""
    app = FastAPI(title="Fractal Tasks Sandbox v2", lifespan=lifespan)

    app.include_router(tasks.router)
    app.include_router(dataset.router)
    app.include_router(project.router)
    app.include_router(run.router)
    app.include_router(workflow.router)
    app.include_router(fs.router)
    app.include_router(params.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    # Serve the built SvelteKit app at the root, if it has been built. Mounted last so
    # it never shadows the /api routes. html=True serves index.html for SPA routes.
    if _FRONTEND_BUILD.is_dir():
        app.mount(
            "/", StaticFiles(directory=_FRONTEND_BUILD, html=True), name="frontend"
        )
        logger.info("Serving frontend from %s", _FRONTEND_BUILD)
    else:
        logger.warning(
            "Frontend build not found at %s — only the API is served. "
            "Run `npm run build` in frontend/.",
            _FRONTEND_BUILD,
        )

    return app


app = create_app()
