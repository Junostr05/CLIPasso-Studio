"""GUI entry point."""

from __future__ import annotations

import os
import sys


def _close_splash() -> None:
    try:
        import pyi_splash  # type: ignore  # only available in the PyInstaller onefile build

        pyi_splash.close()
    except Exception:
        pass


def run_gui(argv: list[str] | None = None) -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication

    from .. import APP_ID, APP_NAME, paths

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv if argv is not None else sys.argv)
    from . import crash

    crash.install()  # crash log + error dialog; a hard crash of the last session is reported below
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setWindowIcon(QIcon(str(paths.resource("app_icon.png"))))

    from . import theme
    from .app_settings import app_settings
    from .i18n import i18n

    settings = app_settings()
    theme.load_fonts()
    theme.apply(app, settings.get("theme"))
    i18n.set_language(settings.get("language"))

    from .main_window import MainWindow

    window = MainWindow()
    app._main_window = window
    window.show()
    _close_splash()
    from PySide6.QtCore import QTimer

    QTimer.singleShot(1200, lambda: crash.show_previous_crash(window))
    QTimer.singleShot(2500, window.check_interrupted_jobs)
    QTimer.singleShot(4000, window.start_update_check)
    return app.exec()
