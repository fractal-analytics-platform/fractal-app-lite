"""Native file/directory dialogs via the pywebview window, with graceful fallback.

``backend.shell`` registers the live pywebview ``Window`` here at startup via
``set_window``. When a native window is present the helpers invoke pywebview OS dialogs;
because ``create_file_dialog`` blocks, the routes call these from a worker threadpool.

When no native window exists — browser / ``pixi run serve`` mode, or the test client —
``has_native_window()`` returns ``False`` and the FS routes tell the frontend to fall
back to a typed-path modal. This mirrors the NiceGUI app's ``files.py`` behaviour.
"""

from pathlib import Path
from typing import Any

# The active pywebview window, set by backend.shell once the window is created.
_window: Any | None = None


def set_window(window: Any) -> None:
    """Register the active pywebview window so the FS dialogs can use it."""
    global _window
    _window = window


def has_native_window() -> bool:
    """Whether a native pywebview window is available for OS dialogs."""
    return _window is not None


def _normalize(result: Any) -> str | None:
    """pywebview returns a tuple/list of paths, a str, or None; collapse to one path."""
    if not result:
        return None
    if isinstance(result, (list, tuple)):
        return str(result[0]) if result else None
    return str(result)


def open_file(file_types: tuple[str, ...] = ("All files (*.*)",)) -> str | None:
    """Pick an existing file to read (native dialog)."""
    import webview

    result = _window.create_file_dialog(  # type: ignore[union-attr]
        dialog_type=webview.FileDialog.OPEN,
        allow_multiple=False,
        file_types=file_types,
    )
    return _normalize(result)


def open_directory() -> str | None:
    """Pick an existing directory (native dialog)."""
    import webview

    result = _window.create_file_dialog(  # type: ignore[union-attr]
        dialog_type=webview.FileDialog.FOLDER,
    )
    return _normalize(result)


def save_file(
    default_name: str = "",
    file_types: tuple[str, ...] = ("All files (*.*)",),
) -> str | None:
    """Pick a destination path to write to (native dialog)."""
    import webview

    result = _window.create_file_dialog(  # type: ignore[union-attr]
        dialog_type=webview.FileDialog.SAVE,
        save_filename=default_name,
        file_types=file_types,
    )
    path = _normalize(result)
    return str(Path(path)) if path is not None else None
