"""Shared fixtures for the fractal-lite test suite."""

import os
import urllib.request
from pathlib import Path

import pytest

from fractal_lite._collect import (
    TasksRegistry,
    TasksRegistryModel,
    tasks_registry,
)

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
def registry(tmp_path):
    """Isolate the ``tasks_registry`` singleton, restoring it after the test.

    ``TasksRegistry`` stores its state in a class attribute, but methods like
    ``load_from_dict`` and ``load_from_json`` set it as an *instance* attribute on the
    singleton, which shadows the class attribute. We save and restore both levels so
    test order does not matter.
    """
    singleton = tasks_registry
    # Pop any instance-level _registry set by a previous test's load_from_dict call.
    old_instance = singleton.__dict__.pop("_registry", None)
    old_class = TasksRegistry._registry
    TasksRegistry._registry = TasksRegistryModel(collection_dir=tmp_path / "collected")
    yield tasks_registry
    TasksRegistry._registry = old_class
    # Remove any instance attribute the test may have set, then restore the old one.
    singleton.__dict__.pop("_registry", None)
    if old_instance is not None:
        singleton._registry = old_instance
