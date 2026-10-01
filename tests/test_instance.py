"""Only one app at a time (gui/instance.py)."""

import os
import subprocess
import sys


def test_a_second_app_is_refused(user_data, qapp):
    from clipasso_studio.gui import instance

    instance.release()
    assert instance.acquire()
    assert instance.acquire()  # the same app asking again
    assert instance.try_lock(instance.lock_path()) is None  # another app
    assert instance.owner_pid(instance.lock_path()) == os.getpid()
    instance.release()
    other = instance.try_lock(instance.lock_path())
    assert other is not None
    other.unlock()


def test_the_lock_of_a_crashed_app_is_taken_over(tmp_path):
    from clipasso_studio.gui import instance

    path = str(tmp_path / "app.lock")
    code = ("import os, sys; from PySide6.QtCore import QLockFile; l = QLockFile(sys.argv[1]); "
            "l.setStaleLockTime(0); assert l.tryLock(100); os._exit(0)")  # ends without unlocking
    subprocess.run([sys.executable, "-c", code, path], check=True, timeout=60)
    assert os.path.exists(path)
    lock = instance.try_lock(path)
    assert lock is not None
    lock.unlock()


def test_bring_to_front_without_a_window():
    from clipasso_studio.gui import instance

    assert not instance.bring_to_front(None)
