"""4.0: the window's header (design system: AppHeader) – the logo and name, the areas *Studio · Gallery · Queue*
(with the number of waiting jobs), the running job, the hardware and the menu **App** (models, settings, compare,
phone, updates, info). It replaces the sidebar of 3.x.

Ctrl+1 … 7 follow what is seen, from left to right: the three areas, then the App menu's pages
(:data:`PAGES`); the menu shows them, but only the window's own shortcuts trigger them."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from ... import paths
from .. import icons, shortcuts, theme
from ..i18n import tr
from .common import Chip, CountBadge, ElidedLabel, label, set_prop

AREAS = (("studio", "brush"), ("gallery", "images"), ("queue", "list-todo"))
# the App menu: (key, icon, page or None); None between groups
APP_ITEMS = (("models", "box", "models"), ("settings", "settings", "settings"), ("compare", "git-compare", "compare"),
             None, ("phone", "smartphone", None), ("updates", "refresh-cw", None), None, ("about", "info", "about"))
PAGES = ("studio", "gallery", "queue", "models", "settings", "compare", "about")  # Ctrl+1 … Ctrl+7


def page_shortcut(page: str) -> str:
    return f"Ctrl+{PAGES.index(page) + 1}"


class HeaderTab(QToolButton):
    """One area of the header: icon and name, and a count on the right (the waiting jobs)."""

    def __init__(self, key: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.key, self.icon_name = key, icon_name
        self.setObjectName("HeaderTab")
        self.setCheckable(True)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(16, 16))
        self.setCursor(Qt.PointingHandCursor)
        self.badge = CountBadge(self)
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.set_count(0)

    def set_count(self, n: int) -> None:
        self.badge.set_count(n)
        set_prop(self, "counted", "true" if n else "false")  # room on the right for the badge
        self._place_badge()
        self.updateGeometry()

    def _place_badge(self) -> None:
        b = self.badge
        b.adjustSize()
        b.move(self.width() - b.width() - 10, (self.height() - b.height()) // 2)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._place_badge()

    def refresh_icon(self) -> None:
        p = theme.current()
        self.setIcon(icons.icon(self.icon_name, p.text if self.isChecked() else p.muted))


class RunChip(QPushButton):
    """The running job in the header: its progress – a click shows it in the studio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RunChip")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(168, 32)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 12, 0)
        lay.setSpacing(8)
        self.icon = QLabel()
        self.label = ElidedLabel("", "muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedSize(56, 4)
        self.bar.setTextVisible(False)
        for w in (self.icon, self.label, self.bar):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self.icon)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.bar)
        self.icon.setPixmap(icons.pixmap("brush", theme.current().accent_text, 14))


class AppHeader(QFrame):
    area_chosen = Signal(str)  # a page of the window
    action_chosen = Signal(str)  # an item of the App menu (APP_ITEMS)
    run_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Header")
        self.setFixedHeight(theme.HEADER_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.COLUMN_PADDING, 0, theme.COLUMN_PADDING, 0)
        lay.setSpacing(theme.SPACE_XL)

        brand = QWidget()
        b = QHBoxLayout(brand)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(10)
        self.logo = QLabel()
        self.logo.setPixmap(icons.QPixmap(str(paths.resource("app_icon.png"))).scaled(
            26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.name = label("CLIPasso Studio", "brand")
        self.byline = label("By: Junostr05", "faint")  # app idea, GUI vision and UI/UX direction
        self.byline.setObjectName("Byline")
        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        names.addStretch(1)
        names.addWidget(self.name)
        names.addWidget(self.byline)
        names.addStretch(1)
        b.addWidget(self.logo)
        b.addLayout(names)
        lay.addWidget(brand)

        nav = QWidget()
        n = QHBoxLayout(nav)
        n.setContentsMargins(0, 0, 0, 0)
        n.setSpacing(theme.SPACE_XS)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.tabs: dict[str, HeaderTab] = {}
        for key, icon_name in AREAS:
            t = HeaderTab(key, icon_name)
            t.clicked.connect(lambda _=False, k=key: self.area_chosen.emit(k))
            t.toggled.connect(lambda _on, tab=t: tab.refresh_icon())
            self.group.addButton(t)
            n.addWidget(t)
            self.tabs[key] = t
        lay.addWidget(nav)
        lay.addStretch(1)

        self.run_chip = RunChip()
        self.run_chip.clicked.connect(self.run_clicked.emit)
        self.run_chip.setVisible(False)
        lay.addWidget(self.run_chip)
        self.hardware = Chip("cpu", "")
        self.hardware.setMaximumWidth(260)
        lay.addWidget(self.hardware)

        self.app_btn = QToolButton()
        self.app_btn.setObjectName("AppButton")
        self.app_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.app_btn.setPopupMode(QToolButton.InstantPopup)
        self.app_btn.setCursor(Qt.PointingHandCursor)
        self.app_btn.setIconSize(QSize(16, 16))
        self.menu = QMenu(self.app_btn)
        self.app_actions: dict[str, QAction] = {}
        for item in APP_ITEMS:
            if item is None:
                self.menu.addSeparator()
                continue
            key, icon_name, page = item
            act = QAction(self.menu)
            act.setIcon(icons.icon(icon_name, theme.current().muted))
            if page is not None:
                act.setShortcut(QKeySequence(page_shortcut(page)))  # shown in the menu …
                act.setShortcutContext(Qt.WidgetShortcut)  # … the window's own shortcut triggers it
            act.triggered.connect(lambda _=False, k=key: self.action_chosen.emit(k))
            self.menu.addAction(act)
            self.app_actions[key] = act
        self.app_btn.setMenu(self.menu)
        lay.addWidget(self.app_btn)
        self.set_hardware(None)
        self.retranslate()

    # ------------------------------------------------------------------ state
    def set_current(self, page: str) -> None:
        """The area of ``page`` is chosen; a page of the App menu: the App button is (none of the areas)."""
        if page in self.tabs:
            self.tabs[page].setChecked(True)
        else:
            self.group.setExclusive(False)
            for t in self.tabs.values():
                t.setChecked(False)
            self.group.setExclusive(True)
        set_prop(self.app_btn, "current", "true" if page not in self.tabs else "false")
        for key, _, p in (i for i in APP_ITEMS if i is not None):
            self.app_actions[key].setCheckable(p is not None)
            self.app_actions[key].setChecked(p == page)
        for t in self.tabs.values():
            t.refresh_icon()

    def set_queue_count(self, n: int) -> None:
        tab = self.tabs["queue"]
        tab.set_count(n)
        tip = shortcuts.with_key(tr("nav.queue"), page_shortcut("queue"))
        tab.setToolTip(f"{tr('ui.queue.pending', n=n)}\n{tip}" if n else tip)
        tab.setAccessibleName(f"{tr('nav.queue')}, {tr('ui.queue.pending', n=n)}" if n else tr("nav.queue"))

    def set_running(self, progress: float | None) -> None:
        """The running job's progress (0..1); None: nothing runs."""
        self.run_chip.setVisible(progress is not None)
        if progress is not None:
            self.run_chip.bar.setValue(int(progress * 1000))
            self.run_chip.label.setText(tr("ui.header.running", percent=int(progress * 100)))
            self.run_chip.setAccessibleName(self.run_chip.label.text())

    def set_hardware(self, info: dict | None) -> None:
        """What the app computes on: the graphics card(s) it can use, else the processor (``hardware.store``)."""
        self._hardware = info
        if info is None:
            self.hardware.set_icon("cpu")
            self.hardware.set_text(tr("ui.header.hw_probing"))
            return
        gpus = [g for g in info.get("gpus") or [] if g.get("supported", True)] if info.get("cuda") else []
        if gpus:
            name = gpus[0].get("name", "GPU").replace("NVIDIA ", "")
            self.hardware.set_icon("microchip")
            self.hardware.set_text(f"{len(gpus)}× {name}" if len(gpus) > 1 else name)
        else:
            self.hardware.set_icon("cpu")
            self.hardware.set_text(tr("ui.header.cpu", n=os.cpu_count() or 1))

    def retranslate(self) -> None:
        for key, t in self.tabs.items():
            t.setText(tr(f"nav.{key}"))
            t.setToolTip(shortcuts.with_key(tr(f"nav.{key}"), page_shortcut(key)))
        self.set_queue_count(self.tabs["queue"].badge.count)
        self.app_btn.setText(tr("ui.header.app"))
        self.app_btn.setToolTip(tr("ui.header.app_tip"))
        self.app_btn.setIcon(icons.icon("ellipsis", theme.current().muted))
        for key, act in self.app_actions.items():
            act.setText(tr(f"ui.app_menu.{key}").replace("&", "&&"))  # ("Info & Hilfe": not a shortcut mark)
        self.run_chip.setToolTip(tr("ui.header.running_tip"))
        self.hardware.setToolTip(tr("ui.header.hw_tip"))
        self.set_hardware(self._hardware)
