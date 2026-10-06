"""The job's progress on the taskbar button: the states, and (Windows) the COM object."""

import sys

import pytest

from clipasso_studio.gui import taskbar


def test_states_for_a_job():
    assert taskbar.state_for("running", 0.42) == (taskbar.NORMAL, 0.42)
    assert taskbar.state_for("running", 0.0) == (taskbar.INDETERMINATE, None)  # (loading the models)
    assert taskbar.state_for("running", 1.3) == (taskbar.NORMAL, 1.0)
    assert taskbar.state_for("paused", 0.5) == (taskbar.PAUSED, 0.5)
    assert taskbar.state_for("failed", 0.3) == (taskbar.ERROR, 1.0)
    assert taskbar.state_for("busy", None) == (taskbar.INDETERMINATE, None)
    assert taskbar.state_for("busy", 0.25) == (taskbar.NORMAL, 0.25)
    for status in ("done", "cancelled", "queued", None):
        assert taskbar.state_for(status, 0.7) == (taskbar.NOPROGRESS, None)


def test_calls_only_when_the_bar_moves(monkeypatch):
    calls = []
    monkeypatch.setattr(taskbar, "_call", lambda obj, index, kinds, *args: calls.append((index, args)))
    bar = taskbar.Taskbar(1234)
    bar._list = object()  # (as on Windows)
    bar.set(taskbar.NORMAL, 0.5)
    bar.set(taskbar.NORMAL, 0.5001)  # less than a step: nothing
    bar.set(taskbar.PAUSED, 0.5)
    bar.clear()
    assert calls == [(taskbar._SET_STATE, (1234, taskbar.NORMAL)), (taskbar._SET_VALUE, (1234, 500, 1000)),
                     (taskbar._SET_STATE, (1234, taskbar.PAUSED)), (taskbar._SET_VALUE, (1234, 500, 1000)),
                     (taskbar._SET_STATE, (1234, taskbar.NOPROGRESS))]


@pytest.mark.skipif(sys.platform == "win32", reason="elsewhere than Windows")
def test_nothing_happens_elsewhere():
    bar = taskbar.Taskbar(1)
    assert not bar.available
    bar.set(taskbar.NORMAL, 0.5)  # (no error)


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows taskbar")
def test_the_windows_taskbar_object():
    from PySide6.QtWidgets import QApplication, QWidget

    QApplication.instance() or QApplication([])
    w = QWidget()
    w.show()
    bar = taskbar.Taskbar(int(w.winId()))
    # CoCreateInstance worked; HrInit needs Explorer's taskbar, which a CI session may not have
    assert bar.available or "call 3 failed" in bar.error, bar.error
    bar.set(taskbar.NORMAL, 0.3)  # (an offscreen window has no button: refused quietly)
    bar.set(taskbar.ERROR, 1.0)
    bar.clear()
    w.close()
