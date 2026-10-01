"""Helpers shared by the GUI tests."""

import time


def wait_until(app, condition, timeout: float = 10.0, step: float = 0.01):
    """Run the event loop until ``condition()`` is true (AssertionError after ``timeout`` seconds)."""
    end = time.time() + timeout
    while not condition():
        if time.time() > end:
            raise AssertionError("timed out")
        app.processEvents()
        time.sleep(step)
