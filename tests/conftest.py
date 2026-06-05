"""Shared fixtures for the fractal-lite test suite."""

import os
import urllib.request
from pathlib import Path

import pytest

from fractal_lite._registry import TasksRegistry, TasksRegistryModel

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data"
CACHE_DIR = DATA_DIR / ".cache"

# Release tarballs the collection/e2e tests need. They are gitignored (``*tar.gz``)
# so a fresh CI checkout downloads them; locally the repo-root copy is reused.
_CONVERTERS_FILE = "fractal_uzh_converters-0.5.2.tar.gz"
_CONVERTERS_URL = os.environ.get(
    "FRACTAL_UZH_CONVERTERS_URL",
    "https://github.com/fractal-analytics-platform/fractal-uzh-converters/"
    "releases/download/v0.5.2/" + _CONVERTERS_FILE,
)


def _locate_or_download(filename: str, url: str) -> Path:
    """Return a path to ``filename``, reusing the repo-root copy or downloading it."""
    local = REPO_ROOT / filename
    if local.is_file():
        return local
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / filename
    if not cached.is_file():
        # Trusted GitHub release URL.
        urllib.request.urlretrieve(url, cached)
    return cached


@pytest.fixture
def converters_targz() -> Path:
    """Path to the fractal-uzh-converters release tarball."""
    return _locate_or_download(_CONVERTERS_FILE, _CONVERTERS_URL)


@pytest.fixture
def registry(tmp_path) -> TasksRegistry:
    """A fresh, isolated :class:`TasksRegistry` collecting into ``tmp_path``.

    Each test gets its own instance (the registry is no longer a global singleton),
    so no save/restore is needed for isolation.
    """
    return TasksRegistry(TasksRegistryModel(collection_dir=tmp_path / "collected"))
