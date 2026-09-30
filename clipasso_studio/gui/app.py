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


UI_SCALES = (0.9, 1.0, 1.1, 1.25, 1.5)


def apply_ui_scale() -> float:
    """Interface size from the settings – must be set before the QApplication exists."""
    from .app_settings import app_settings

    try:
        scale = float(app_settings().get("ui_scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    scale = min(max(scale, 0.75), 2.0)
    if abs(scale - 1.0) > 1e-3 and "QT_SCALE_FACTOR" not in os.environ:  # an explicit variable wins
        os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
    return scale


def restart_command() -> tuple[str, list[str]]:
    """How to start this app again (exe, or ``python -m clipasso_studio`` from source)."""
    args = [a for a in sys.argv[1:]]
    if getattr(sys, "frozen", False):
        return sys.executable, args
    return sys.executable, ["-m", "clipasso_studio"] + args


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
    apply_ui_scale()
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
