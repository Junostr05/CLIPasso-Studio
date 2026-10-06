"""Keyboard shortcuts of the main window (also listed on the About page)."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

# (key sequence, i18n key of the description); Ctrl+Return also answers to Ctrl+Enter (keypad)
SHORTCUTS = (
    ("Ctrl+O", "ui.shortcut.open"),
    ("Ctrl+V", "ui.shortcut.paste"),
    ("Ctrl+Return", "ui.shortcut.start"),
    ("Ctrl+Shift+Return", "ui.shortcut.queue"),
    ("Ctrl+E", "ui.shortcut.export"),
    ("Ctrl+C", "ui.shortcut.copy"),
    ("Ctrl+Z", "ui.shortcut.undo"),
    ("Ctrl+Y", "ui.shortcut.redo"),
    ("Ctrl+1", "ui.shortcut.pages"),
    ("F11", "ui.shortcut.focus"),
)


def native(sequence: str) -> str:
    """The key sequence as the platform writes it (Ctrl+O, ⌘O …)."""
    return QKeySequence(sequence).toString(QKeySequence.NativeText)


def with_key(text: str, sequence: str) -> str:
    return f"{text}  ({native(sequence)})"
