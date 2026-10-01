"""Shared test setup: offscreen Qt, one QApplication for all tests, a fresh app data folder on request
and time limits (a hanging test fails instead of blocking the run)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SLOW_TIMEOUT = 3600  # s, end-to-end runs (the default limit is in pyproject.toml)


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.get_closest_marker("slow") and not item.get_closest_marker("timeout"):
            item.add_marker(pytest.mark.timeout(SLOW_TIMEOUT))


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def user_data(tmp_path, monkeypatch):
    """An empty app data folder (settings, caches, edited masks) for one test."""
    data = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("LOCALAPPDATA", str(data))
    return data
