"""Shared test setup: offscreen Qt, one QApplication for all tests, a fresh app data folder on request
and time limits (a hanging test fails instead of blocking the run)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SLOW_TIMEOUT = 3600  # s, end-to-end runs (the default limit is in pyproject.toml)
# CI: a file for the memory before every test – a process that runs out of memory can end without a word
# (OpenBLAS calls exit(1)); the last lines show where it was, the summary how close a passing run came
MEMLOG = os.environ.get("CLIPASSO_TEST_MEMLOG")
_peaks: list[tuple[int, int, int, str]] = []


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


def _memory() -> tuple[int, int, int, int]:
    """(this process's committed memory, the system's commit, its limit, processes) in bytes; Windows counts
    what is reserved, not only what is used (other systems: resident memory, used and total RAM)."""
    import psutil

    proc = psutil.Process().memory_info()
    if os.name != "nt":
        vm = psutil.virtual_memory()
        return proc.rss, vm.total - vm.available, vm.total, len(psutil.pids())
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
            "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable", "SystemCache",
            "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize")] + [
            (n, wintypes.DWORD) for n in ("HandleCount", "ProcessCount", "ThreadCount")]

    info = Info(cb=ctypes.sizeof(Info))
    ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb)
    page = info.PageSize
    return getattr(proc, "private", proc.vms), info.CommitTotal * page, info.CommitLimit * page, info.ProcessCount


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    if not MEMLOG:
        return
    mine, used, limit, procs = _memory()
    _peaks.append((mine, used, limit, item.nodeid))
    gb = 2 ** 30
    with open(MEMLOG, "a", encoding="utf-8") as f:
        f.write(f"{mine / gb:6.2f} GB  system {used / gb:6.2f} of {limit / gb:6.2f} GB  {procs:4d} processes  "
                f"{item.nodeid}\n")


def pytest_terminal_summary(terminalreporter):
    if MEMLOG and _peaks:
        gb = 2 ** 30
        used, limit, nodeid = max((u, lim, n) for _, u, lim, n in _peaks)
        terminalreporter.write_line(f"memory: the system at most {used / gb:.2f} of {limit / gb:.2f} GB (before "
                                    f"{nodeid}); the test process at most: " + ", ".join(
            f"{m / gb:.2f} GB before {n}" for m, _, _, n in sorted(_peaks, reverse=True)[:3]))
