"""Curated index of known Fractal task packages.

Maps a distribution ``pkg_name`` (e.g. ``fractal-tasks-core``) to the GitHub
repository it is released from. This is what lets a Fractal-format workflow —
which references tasks only by ``pkg_name``/``version``/``name`` — be resolved
back into runnable tasks by collecting the matching GitHub release.
"""

import json
from pathlib import Path

from pydantic import BaseModel

_PACKAGE_INDEX = Path(__file__).parent / "resources" / "package_index.json"


class PackageIndexEntry(BaseModel):
    """One curated GitHub-release task package."""

    pkg_name: str
    repo_url: str
    # Pinned release tag; empty/None means collect the latest release.
    tag: str | None = None
    description: str = ""


def load_package_index() -> list[PackageIndexEntry]:
    """Load the bundled curated package index (empty list if absent)."""
    if not _PACKAGE_INDEX.is_file():
        return []
    return [PackageIndexEntry(**e) for e in json.loads(_PACKAGE_INDEX.read_text())]


def find_package(pkg_name: str) -> PackageIndexEntry | None:
    """Return the index entry for ``pkg_name``, or ``None`` if not listed."""
    for entry in load_package_index():
        if entry.pkg_name == pkg_name:
            return entry
    return None
