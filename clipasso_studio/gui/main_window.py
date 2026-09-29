"""Main window: navigation rail + pages."""

from __future__ import annotations

import sys

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QProgressBar, QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, paths
from . import icons, theme
from .app_settings import app_settings
from .controller import JobController
from .i18n import i18n, tr
from .pages.compare import ComparePage
from .pages.other_pages import AboutPage, GalleryPage, ModelsPage, QueuePage, SettingsPage
from .pages.studio import StudioPage
from .widgets.common import Toast, label

NAV = (
    ("studio", "brush"),
    ("compare", "git-compare"),
    ("queue", "list-todo"),
    ("gallery", "images"),
    ("models", "box"),
    ("settings", "settings"),
    ("about", "info"),
)


def _dark_title_bar(window: QWidget, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(paths.resource("app_icon.png"))))
        self.setMinimumSize(1080, 660)
        self.resize(1440, 900)
        self.controller = JobController(self)

        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ------------------------------------------------------------- sidebar
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(104)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(6, 16, 6, 16)
        sv.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(icons.QPixmap(str(paths.resource("app_icon.png"))).scaled(
            40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        sv.addWidget(logo)
        brand = label("CLIPasso", "faint")
        brand.setAlignment(Qt.AlignCenter)
        sv.addWidget(brand)
        sv.addSpacing(14)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, QToolButton] = {}
        for key, ic in NAV:
            b = QToolButton()
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(22, 22))
            b.setFixedSize(92, 62)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            if key == "settings":
                sv.addStretch(1)
                self.run_indicator = QWidget()
                ri = QVBoxLayout(self.run_indicator)
                ri.setContentsMargins(2, 0, 2, 8)
                ri.setSpacing(4)
                self.run_label = label("", "faint")
                self.run_label.setAlignment(Qt.AlignCenter)
                self.run_bar = QProgressBar()
                self.run_bar.setRange(0, 1000)
                self.run_bar.setFixedHeight(5)
                self.run_bar.setTextVisible(False)
                ri.addWidget(self.run_label)
                ri.addWidget(self.run_bar)
                self.run_indicator.setVisible(False)
                self.run_indicator.setCursor(Qt.PointingHandCursor)
                self.run_indicator.mouseReleaseEvent = lambda e: self.show_page("studio")
                sv.addWidget(self.run_indicator)
            sv.addWidget(b, 0, Qt.AlignHCenter)
        h.addWidget(side)

        # --------------------------------------------------------------- pages
        self.stack = QStackedWidget()
        self.studio = StudioPage(self.controller)
        self.compare = ComparePage(self.controller, self.studio)
        self.queue = QueuePage(self.controller, lambda: self.studio.params.settings())
        self.gallery = GalleryPage()
        self.models = ModelsPage()
        self.settings = SettingsPage()
        self.about = AboutPage()
        self.pages = {"studio": self.studio, "compare": self.compare, "queue": self.queue, "gallery": self.gallery,
                      "models": self.models, "settings": self.settings, "about": self.about}
        for p in self.pages.values():
            self.stack.addWidget(p)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.toast = Toast(root)
        self.studio.toast.connect(self.toast.show_message)
        self.studio.open_queue.connect(lambda: self.show_page("queue"))
        self.gallery.open_job.connect(self._open_job)
        self.compare.open_job.connect(self._open_job)
        self.compare.toast.connect(self.toast.show_message)
        self.settings.theme_changed.connect(self.apply_theme)
        self.controller.job_event.connect(self._on_job_event)
        self.controller.job_finished.connect(self._on_job_finished)
        self.controller.queue_changed.connect(self._update_nav_badges)
        i18n.language_changed.connect(lambda _: self.retranslate())

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)

        self.retranslate()
        self.show_page("studio")
        geo = app_settings().get("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        QTimer.singleShot(0, lambda: _dark_title_bar(self, theme.current().name == "dark"))

    # ---------------------------------------------------------------- actions
    def show_page(self, key: str):
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)
        self._refresh_nav_icons()

    def _open_job(self, job_dir: str):
        self.studio.show_job_dir(job_dir)
        self.show_page("studio")

    def _refresh_nav_icons(self):
        p = theme.current()
        pending = len(self.controller.pending())
        for key, ic in NAV:
            b = self.nav_buttons[key]
            color = p.text if b.isChecked() else p.muted
            if key == "queue" and pending:
                b.setIcon(QIcon(self._badged(ic, color, pending)))
            else:
                b.setIcon(icons.icon(ic, color))

    @staticmethod
    def _badged(name: str, color: str, count: int):
        """Nav icon with a small count bubble in the top right corner."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QPainter

        pm = icons.pixmap(name, color, 22)
        dpr = pm.devicePixelRatio()
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.current().accent))
        rect = QRectF(11, -1, 13, 13)
        painter.drawEllipse(rect)
        font = QFont(theme.FONT_FAMILY)
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignCenter, str(count) if count < 10 else "9+")
        painter.end()
        pm.setDevicePixelRatio(dpr)
        return pm

    def apply_theme(self, mode: str):
        theme.apply(QApplication.instance(), mode)
        # rebuild the window so every custom-painted widget picks up the new palette
        geo = self.saveGeometry()
        current = next(k for k, w in self.pages.items() if w is self.stack.currentWidget())
        if self.controller.is_busy():
            self._refresh_nav_icons()
            self.toast.show_message(tr("ui.theme_after_run"), "info")
            return
        new = MainWindow()
        new.restoreGeometry(geo)
        new.show()
        new.show_page(current)
        QApplication.instance()._main_window = new
        self.controller.shutdown()
        self._closing_for_theme = True
        self.close()

    def _update_nav_badges(self):
        n = len(self.controller.pending())
        self.nav_buttons["queue"].setToolTip(tr("ui.queue.pending", n=n) if n else "")
        self._refresh_nav_icons()

    def _on_job_event(self, job, kind, data):
        if kind == "iteration":
            self.run_indicator.setVisible(True)
            self.run_bar.setValue(int(job.progress * 1000))
            self.run_label.setText(f"{int(job.progress * 100)} %")

    def _on_job_finished(self, job):
        self.run_indicator.setVisible(self.controller.is_busy())
        if app_settings().get("notify") and not self.isActiveWindow():
            QApplication.alert(self)
            if self.tray is not None:
                self.tray.show()
                if job.status == "done":
                    self.tray.showMessage(tr("ui.notify_done_title"), tr("ui.toast_done", name=job.name),
                                          QSystemTrayIcon.Information, 8000)
                else:
                    self.tray.showMessage(tr("ui.notify_failed_title"), job.message or job.status,
                                          QSystemTrayIcon.Warning, 8000)

    def retranslate(self):
        for key, _ in NAV:
            self.nav_buttons[key].setText(tr(f"nav.{key}"))
        self._update_nav_badges()
        self._refresh_nav_icons()

    # ------------------------------------------------------------------ events
    def closeEvent(self, event):  # noqa: N802
        if getattr(self, "_closing_for_theme", False):
            event.accept()
            return
        if self.controller.is_busy():
            res = QMessageBox.question(self, APP_NAME, tr("ui.quit_running"))
            if res != QMessageBox.Yes:
                event.ignore()
                return
        app_settings().set("geometry", bytes(self.saveGeometry().toBase64()).decode())
        self.controller.shutdown()
        event.accept()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.toast.isVisible():
            par = self.toast.parentWidget()
            self.toast.move(par.width() - self.toast.width() - 24, par.height() - self.toast.height() - 24)
