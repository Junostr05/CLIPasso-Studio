"""Main window: navigation rail + pages."""

from __future__ import annotations

import json
import os
import sys

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QProgressBar, QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, paths
from . import dialogs, icons, methods_ui, shortcuts, theme, updates
from .app_settings import app_settings
from .controller import JobController
from .i18n import i18n, tr
from .pages.compare import ComparePage
from .pages.other_pages import AboutPage, GalleryPage, ModelsPage, QueuePage, SettingsPage
from .pages.studio import StudioPage
from .widgets.common import Toast, button, label, tool_button

NAV = (
    ("studio", "brush"),
    ("compare", "git-compare"),
    ("queue", "list-todo"),
    ("gallery", "images"),
    ("models", "box"),
    ("settings", "settings"),
    ("about", "info"),
)


class UpdateBar(QFrame):
    """"CLIPasso Studio x.y is available" – with Download, Skip this version and close."""

    skipped = Signal(str)
    install_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.release: dict = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.install = button("", "download", "primary")
        self.install.clicked.connect(lambda: self.install_requested.emit(self.release))
        self.download = button("", "external-link", "ghost")
        self.download.clicked.connect(self._download)
        self.skip = button("", None, "ghost")
        self.skip.clicked.connect(self._skip)
        self.close_btn = tool_button("x")
        self.close_btn.clicked.connect(self.hide_bar)
        lay.addWidget(self.icon, 0, Qt.AlignVCenter)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.skip)
        lay.addWidget(self.download)
        lay.addWidget(self.install)
        lay.addWidget(self.close_btn)

    def show_release(self, release: dict) -> None:
        self.release = release
        self.retranslate()
        self.parentWidget().show()

    def hide_bar(self) -> None:
        self.parentWidget().hide()

    def _download(self):
        QDesktopServices.openUrl(QUrl(self.release.get("url") or updates.RELEASES_PAGE))
        self.hide_bar()

    def _skip(self):
        self.skipped.emit(self.release.get("tag", ""))
        self.hide_bar()

    def retranslate(self):
        p = theme.current()
        self.icon.setPixmap(icons.pixmap("sparkles", p.accent_hover, 18))
        version = self.release.get("tag", "").lstrip("v")
        self.text.setText(tr("ui.update.available", version=version, current=__version__))
        can = bool(self.release) and updates.can_install(self.release)
        self.install.setVisible(can)
        self.install.setText(tr("ui.update.install"))
        self.download.setProperty("variant", "ghost" if can else "primary")
        self.download.style().unpolish(self.download)
        self.download.style().polish(self.download)
        self.download.setText(tr("ui.update.download"))
        self.skip.setText(tr("ui.update.skip"))
        self.close_btn.setToolTip(tr("ui.update.later"))


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
        if float(app_settings().get("ui_scale", 1.0)) > 1.0:  # larger interface: still fit the screen
            screen = QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                self.setMinimumSize(min(1080, int(avail.width() * 0.9)), min(660, int(avail.height() * 0.85)))
                self.resize(min(1440, int(avail.width() * 0.95)), min(900, int(avail.height() * 0.9)))
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
        self.byline = label("By: Junostr05", "faint")  # app idea, GUI vision and UI/UX direction
        self.byline.setObjectName("Byline")
        self.byline.setAlignment(Qt.AlignCenter)
        self.byline.setStyleSheet("font-size: 9px;")
        sv.addWidget(self.byline)
        sv.addSpacing(12)
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
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.update_wrap = QWidget()
        uw = QVBoxLayout(self.update_wrap)
        uw.setContentsMargins(24, 14, 24, 0)
        self.update_bar = UpdateBar(self.update_wrap)
        self.update_bar.skipped.connect(lambda tag: app_settings().set("skipped_version", tag))
        self.update_bar.install_requested.connect(self.install_update)
        uw.addWidget(self.update_bar)
        self.update_wrap.hide()
        cv.addWidget(self.update_wrap)
        cv.addWidget(self.stack, 1)
        h.addWidget(content, 1)
        self.setCentralWidget(root)

        self.toast = Toast(root)
        self.studio.toast.connect(self.toast.show_message)
        self.studio.open_queue.connect(lambda: self.show_page("queue"))
        self.gallery.open_job.connect(self._open_job)
        self.gallery.job_deleted.connect(self.studio.forget_job_dir)
        self.gallery.continue_job.connect(self.continue_job)
        self.compare.open_job.connect(self._open_job)
        self.compare.toast.connect(self.toast.show_message)
        self.gallery.toast.connect(self.toast.show_message)
        self.settings.theme_changed.connect(self.apply_theme)
        self.controller.job_event.connect(self._on_job_event)
        self.controller.job_finished.connect(self._on_job_finished)
        self.controller.queue_changed.connect(self._update_nav_badges)
        i18n.language_changed.connect(lambda _: self.retranslate())

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)

        self._install_shortcuts()
        self.retranslate()
        self.show_page("studio")
        geo = app_settings().get("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        QTimer.singleShot(0, lambda: _dark_title_bar(self, theme.current().name == "dark"))

    def restart_app(self) -> bool:
        """Close (asks if a job is running) and start again, e.g. for a new interface size."""
        from PySide6.QtCore import QProcess

        from .app import restart_command

        if not self.close():
            return False
        program, args = restart_command()
        QProcess.startDetached(program, args)
        QApplication.quit()
        return True

    def install_update(self, release: dict) -> bool:
        """Download the update, then close and run the installer (or start the new portable exe)."""
        from PySide6.QtCore import QProcess

        edition, mode = updates.build_info()
        dlg = dialogs.UpdateDownloadDialog(release, self)
        if dlg.exec() != dialogs.QDialog.Accepted or not dlg.path:
            return False
        version = release.get("tag", "").lstrip("v")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(APP_NAME)
        box.setText(tr("ui.update.ready", version=version))
        box.setInformativeText(tr(f"ui.update.ready_{mode}"))
        now = box.addButton(tr("ui.update.install_now"), QMessageBox.AcceptRole)
        box.addButton(tr("ui.later"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not now:
            return False
        path = updates.place_portable(dlg.path, version) if mode == "portable" else dlg.path
        program, args = updates.install_command(path, mode)
        if not self.close():  # a running job: the user decided to keep it
            return False
        QProcess.startDetached(program, args)
        QApplication.quit()
        return True

    # ------------------------------------------------------ interrupted jobs
    def continue_job(self, job_dir: str) -> bool:
        job = self.controller.continue_job(job_dir)
        if job is None:
            self.toast.show_message(tr("ui.resume.nothing"), "info")
            return False
        self.toast.show_message(tr("ui.resume.queued"), "success")
        self.show_page("studio" if self.controller.current is job else "queue")
        return True

    def check_interrupted_jobs(self) -> list[str]:
        """After the start: offer to continue jobs that were running when the app was closed or crashed.
        Asked once per job; afterwards the Gallery keeps offering "Continue"."""
        from ..engine import jobs
        from .pages.other_pages import scan_jobs

        found = [(d, s) for d, s in scan_jobs(unfinished=True)
                 if s.get("state") in ("running", "interrupted") and jobs.summary_can_continue(s)
                 and not jobs.read_state(d).get("asked")]
        if not found:
            return []
        for d, _ in found:
            jobs.mark_asked(d)
        lines = []
        for d, s in found[:6]:
            done, total = s["progress"]
            name = os.path.splitext(os.path.basename(s.get("target", d)))[0]
            lines.append(f"• {name} – {methods_ui.name(s.get('method', 'clipasso'))} ({done}/{total})")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(APP_NAME)
        box.setText(tr("ui.resume.startup_title", n=len(found)))
        box.setInformativeText(tr("ui.resume.startup_text") + "\n\n" + "\n".join(lines))
        yes = box.addButton(tr("ui.continue"), QMessageBox.AcceptRole)
        box.addButton(tr("ui.later"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            for d, _ in found:
                self.controller.continue_job(d)
            self.show_page("studio")
        return [d for d, _ in found]

    # -------------------------------------------------------------- shortcuts
    def _install_shortcuts(self):
        self.shortcuts: dict[str, QShortcut] = {}

        def add(sequence, handler):
            sc = QShortcut(QKeySequence(sequence), self)
            sc.activated.connect(handler)
            self.shortcuts[sequence] = sc

        add("Ctrl+O", self._shortcut_open)
        add("Ctrl+V", self._shortcut_paste)  # text fields keep their own Ctrl+V (Qt gives it to them first)
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            add(seq, self._shortcut_start)
        for seq in ("Ctrl+Shift+Return", "Ctrl+Shift+Enter"):
            add(seq, self._shortcut_queue)
        add("Ctrl+E", self._shortcut_export)
        add("Ctrl+C", self._shortcut_copy)  # text fields keep their own Ctrl+C
        add("Ctrl+Z", self.studio.undo_edit)  # eraser (text fields keep their own undo)
        for seq in ("Ctrl+Y", "Ctrl+Shift+Z"):
            add(seq, self.studio.redo_edit)
        for i, (key, _) in enumerate(NAV):
            add(f"Ctrl+{i + 1}", lambda k=key: self.show_page(k))

    def _shortcut_open(self):
        self.show_page("studio")
        self.studio.browse_image()

    def _shortcut_paste(self):
        if self.studio.paste_image():
            self.show_page("studio")

    def _shortcut_start(self):
        if self.studio.start_btn.isEnabled():
            self.show_page("studio")
            self.studio.start()

    def _shortcut_queue(self):
        if self.studio.image_path:
            self.show_page("studio")
            self.studio.add_to_queue()

    def _shortcut_copy(self):
        if self.stack.currentWidget() is self.studio:
            self.studio.copy_sketch()

    def _shortcut_export(self):
        if self.studio.export_btns["svg"].isEnabled():
            self.show_page("studio")
            self.studio.export("svg")

    # ---------------------------------------------------------------- updates
    def start_update_check(self, url: str = updates.RELEASES_API):
        """Look for a newer release in the background (if enabled in the settings)."""
        if app_settings().get("check_updates"):
            dialogs.run_in_thread(self, updates.check, url=url, on_done=self._update_found)

    def _update_found(self, text: str):
        try:
            release = json.loads(text) if text else None
        except ValueError:
            release = None
        if release and release.get("tag") != app_settings().get("skipped_version"):
            self.update_bar.show_release(release)

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
        self.studio.shutdown()
        self.controller.shutdown()
        self._closing_for_theme = True
        self.close()

    def _update_nav_badges(self):
        n = len(self.controller.pending())
        for i, (key, _) in enumerate(NAV):
            tip = shortcuts.with_key(tr(f"nav.{key}"), f"Ctrl+{i + 1}")
            if key == "queue" and n:
                tip = f"{tr('ui.queue.pending', n=n)}\n{tip}"
            self.nav_buttons[key].setToolTip(tip)
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
        self.studio.open_btn.setToolTip(shortcuts.with_key(tr("ui.shortcut.open"), "Ctrl+O"))
        self.studio.start_btn.setToolTip(shortcuts.with_key(tr("ui.shortcut.start"), "Ctrl+Return"))
        self.studio.queue_btn.setToolTip(shortcuts.with_key(tr("ui.shortcut.queue"), "Ctrl+Shift+Return"))
        self.studio.export_btns["svg"].setToolTip(shortcuts.with_key(tr("ui.shortcut.export"), "Ctrl+E"))
        if self.update_bar.release:
            self.update_bar.retranslate()
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
        self.studio.shutdown()
        self.controller.shutdown()
        dialogs.wait_for_threads()
        event.accept()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.toast.isVisible():
            par = self.toast.parentWidget()
            self.toast.move(par.width() - self.toast.width() - 24, par.height() - self.toast.height() - 24)
