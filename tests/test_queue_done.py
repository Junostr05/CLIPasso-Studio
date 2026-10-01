"""When the queue is done: sleep / shut down after a countdown (only once, only if chosen)."""

import time

import pytest


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import dialogs, theme
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp_path / "out")
    theme.apply(QApplication.instance(), "dark")
    monkeypatch.setattr(dialogs.CountdownDialog, "SECONDS", 1)
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.controller.start_next = lambda: None
    done = []
    w.power_action = done.append
    yield w, done
    w.studio.shutdown()
    w.controller.shutdown()
    w.close()
    settings_module._instance = None


class _Job:
    status = "done"


def test_nothing_happens_by_default_or_without_a_run(window):
    w, done = window
    w.controller.queue_idle.emit(_Job())
    assert done == []
    w.queue.set_done_action("shutdown")  # chosen, but no job ran since
    w.controller.queue_idle.emit(_Job())
    assert done == []


def test_countdown_then_action_once(window, monkeypatch):
    from PySide6.QtWidgets import QApplication

    w, done = window
    w.queue.set_done_action("sleep")
    w.controller.job_started.emit(_Job())  # a job ran after the choice
    w.controller.queue_idle.emit(_Job())  # the countdown (1 s here) runs its own event loop
    QApplication.processEvents()
    assert done == ["sleep"] and w.queue.done_action() == "nothing"  # reset: once per choice
    w.controller.queue_idle.emit(_Job())
    assert done == ["sleep"]


def test_countdown_can_be_cancelled(window, monkeypatch):
    from PySide6.QtCore import QTimer

    from clipasso_studio.gui import dialogs

    w, done = window
    monkeypatch.setattr(dialogs.CountdownDialog, "SECONDS", 30)
    w.queue.set_done_action("shutdown")
    w.queue.ran_since_choice = True

    def cancel():
        for dlg in w.findChildren(dialogs.CountdownDialog):
            assert "30" in dlg.text.text() or "29" in dlg.text.text()
            dlg.reject()

    QTimer.singleShot(300, cancel)
    start = time.time()
    w.controller.queue_idle.emit(_Job())
    assert done == [] and time.time() - start < 5 and w.queue.done_action() == "nothing"


def test_controller_signals_idle_only_when_the_queue_ran_out(tmp_path, monkeypatch):
    from clipasso_studio.gui.controller import JobController, QueuedJob

    c = JobController()
    idle = []
    c.queue_idle.connect(idle.append)

    class Runner:
        def poll(self):
            return []

        def is_running(self):
            return False

    c.runner = Runner()
    for status, queued_after, expected in (("done", False, 1), ("failed", False, 1), ("cancelled", False, 0),
                                           ("done", True, 0)):
        idle.clear()
        job = QueuedJob(target="a.png", settings={})
        job.status = status
        c.jobs = [job]
        if queued_after:
            c.jobs.append(QueuedJob(target="b.png", settings={}))
        c.current = job
        c.auto_start = False
        c._poll()
        assert len(idle) == expected, (status, queued_after)


def test_power_is_a_no_op_off_windows(monkeypatch):
    from clipasso_studio.gui import power

    monkeypatch.setattr(power.sys, "platform", "linux")
    assert not power.available() and power.run("shutdown") is False
