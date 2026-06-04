"""Native desktop entrypoint: run uvicorn in a thread, open a pywebview window.

This replaces NiceGUI's ``ui.run(native=True, ...)``. The FastAPI app serves both the
API and the built Svelte frontend on a localhost port; pywebview opens a borderless
native window pointed at it (the brief's §2/§3 — pywebview is BSD-3, no CORS, one
process). Launch with ``pixi run app`` or ``python -m backend.shell``.
"""

import argparse
import logging
import socket
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import uvicorn
import webview

from backend import fs
from backend import session as session_io
from backend.main import app

logger = logging.getLogger(__name__)

_HOST = "127.0.0.1"
_TITLE = "Fractal Lite"
_WINDOW_SIZE = (1280, 900)


def _free_port() -> int:
    """Pick an OS-assigned free TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_HOST, 0))
        return s.getsockname()[1]


def _run_server(port: int) -> None:
    """Run uvicorn on ``port`` (blocking; called in a daemon thread)."""
    uvicorn.run(app, host=_HOST, port=port, log_level="info")


def _wait_until_ready(url: str, timeout: float = 30.0) -> bool:
    """Poll the health endpoint until the server answers (or time out)."""
    deadline = time.monotonic() + timeout
    health = f"{url}/api/health"
    while time.monotonic() < deadline:
        try:
            with urlopen(health, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def _resume_session(path: str) -> None:
    """Restore a saved session at startup.

    ``load_session`` rehydrates the registry from the bundle's stored sources
    (re-parsing them) and re-resolves the workflow, all best-effort, so a resume
    still succeeds if a task source has moved.
    """
    try:
        session_io.load_session(path)
        logger.info("Resumed session from %s", path)
    except Exception as exc:
        logger.error("Failed to resume from %s: %s — starting fresh.", path, exc)


def main() -> None:
    """Start the API server in the background, then open the native window."""
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="fractal-lite-app")
    parser.add_argument(
        "--resume",
        metavar="STATE_JSON",
        help="Restore a session saved with the app's 'Save session' button.",
    )
    args, _ = parser.parse_known_args()

    port = _free_port()
    url = f"http://{_HOST}:{port}"

    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    if not _wait_until_ready(url):
        raise RuntimeError(f"Backend did not become ready at {url}")
    logger.info("Backend ready at %s", url)

    # The registry starts empty; a --resume bundle restores a saved registry and
    # dataset before the window opens.
    if args.resume and Path(args.resume).is_file():
        _resume_session(args.resume)
    elif args.resume:
        logger.error("Resume file not found: %s — starting fresh.", args.resume)

    window = webview.create_window(
        _TITLE, url, width=_WINDOW_SIZE[0], height=_WINDOW_SIZE[1]
    )
    # Expose the window to the FS dialog bridge so the frontend can open native
    # file/dir dialogs through the backend.
    fs.set_window(window)
    webview.start()  # blocks until the window is closed; uvicorn thread is a daemon


if __name__ == "__main__":
    main()
