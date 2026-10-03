"""The PyTorch for older graphics cards (``gpu_runtime``) in the window: offered once when the hardware probe
finds a card the bundled PyTorch cannot use (GTX 10xx …), downloaded with progress, switched on and off in
the settings. A change takes effect at the next start."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QProgressBar, QVBoxLayout

from .. import APP_NAME, gpu_runtime
from .app_settings import app_settings
from .dialogs import run_in_thread, set_progress
from .i18n import tr
from .widgets.common import button, label

DISMISSED = "gpu_runtime_dismissed"  # app setting: "don't ask again" for this runtime


def available_here() -> bool:
    """Only the GPU edition for Windows can use it (the runtime is PyTorch for Windows)."""
    from .updates import build_info

    return build_info()[0] == "gpu"


def state() -> str:
    """"active" | "restart" (switched on, used after the next start) | "off" (installed) | "missing"."""
    if gpu_runtime.active():
        return "active"
    if gpu_runtime.is_installed():
        return "restart" if app_settings().get(gpu_runtime.SETTING) == gpu_runtime.LEGACY.name else "off"
    return "missing"


def gb(n: int) -> str:
    """Gigabytes with one decimal, with a decimal comma in German."""
    from .i18n import i18n

    text = f"{n / 1e9:.1f}"
    return text.replace(".", ",") if i18n.lang == "de" else text


class RuntimeDownloadDialog(QDialog):
    """Downloads, checks and unpacks the runtime with progress and cancel."""

    def __init__(self, parent=None, root=None):
        super().__init__(parent)
        self.root = root
        self.ok = False
        self.busy = False
        self._cancel = False
        self._phase = {"name": "download"}
        rt = gpu_runtime.LEGACY
        self.setWindowTitle(tr("ui.gpurt.title"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(label(tr("ui.gpurt.title"), "h2"))
        lay.addWidget(label(tr("ui.gpurt.dialog_desc", download=gb(rt.download_size), disk=gb(rt.unpacked)),
                            "muted", wrap=True))
        self.status = label("", "faint")
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button(tr("ui.cancel"), variant="ghost")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

    def _progress(self, done, total):
        set_progress(self.bar, done, total)
        name = self._phase["name"]
        if total <= 0 or name == "check":
            self.status.setText(tr("ui.gpurt.checking"))
        elif name == "unpack":
            self.status.setText(tr("ui.gpurt.unpacking", percent=int(100 * done / max(total, 1))))
        else:
            self.status.setText(tr("ui.gpurt.progress", done=f"{done / 1e6:.0f}", total=f"{total / 1e6:.0f}"))

    def start(self):
        self.busy = True
        self.status.setText(tr("ui.gpurt.downloading"))

        def done(_path):
            self.busy = False
            self.ok = not self._cancel
            (self.accept if self.ok else super(RuntimeDownloadDialog, self).reject)()

        def failed(msg):
            self.busy = False
            if not self._cancel:
                QMessageBox.warning(self, tr("ui.error"), msg)
            super(RuntimeDownloadDialog, self).reject()

        run_in_thread(self, gpu_runtime.install, root=self.root, cancel=lambda: self._cancel,
                      phase=lambda name: self._phase.__setitem__("name", name),
                      on_progress=self._progress, on_done=done, on_error=failed)

    def exec(self):  # noqa: A003 – the download starts with the dialog
        QTimer.singleShot(0, self.start)
        return super().exec()

    def reject(self):
        if self.busy:  # stops; what is downloaded stays for the next try
            self._cancel = True
            self.cancel_btn.setEnabled(False)
            self.status.setText(tr("ui.cancelling"))
            return
        super().reject()


def download(parent) -> bool:
    """Download and switch on the runtime; then offer to restart. True when it is installed."""
    dlg = RuntimeDownloadDialog(parent)
    if not dlg.exec() or not dlg.ok:
        return False
    switch(True)
    ask_restart(parent)
    return True


def switch(on: bool) -> None:
    app_settings().set(gpu_runtime.SETTING, gpu_runtime.LEGACY.name if on else "")


def ask_restart(parent) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(APP_NAME)
    box.setText(tr("ui.gpurt.restart"))
    now = box.addButton(tr("ui.settings.restart"), QMessageBox.AcceptRole)
    box.addButton(tr("ui.later"), QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is now and hasattr(parent.window(), "restart_app"):
        return bool(parent.window().restart_app())
    return False


def ask(parent, gpu_name: str, again: bool) -> str:
    """"load" | "later" | "never"."""
    rt = gpu_runtime.LEGACY
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(APP_NAME)
    box.setText(tr("ui.gpurt.offer_again" if again else "ui.gpurt.offer", gpu=gpu_name))
    box.setInformativeText(tr("ui.gpurt.offer_text", download=gb(rt.download_size), disk=gb(rt.unpacked)))
    load = box.addButton(tr("ui.gpurt.load"), QMessageBox.AcceptRole)
    never = box.addButton(tr("ui.gpurt.never"), QMessageBox.DestructiveRole)
    box.addButton(tr("ui.later"), QMessageBox.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    return "load" if clicked is load else "never" if clicked is never else "later"


def should_offer(info: dict | None) -> list[str]:
    """The GPUs to offer the runtime for after a hardware probe ([] = nothing to ask)."""
    names = gpu_runtime.helps(info)
    if not names or not available_here() or gpu_runtime.active():
        return []
    s = app_settings()
    if s.get(DISMISSED) == gpu_runtime.LEGACY.name or state() in ("restart", "off"):
        return []  # declined, switched off by the user, or used after the next start
    return names


def offer(parent, info: dict | None) -> str | None:
    """After the hardware probe: ask once whether to load the runtime (None: nothing asked)."""
    names = should_offer(info)
    if not names:
        return None
    again = bool(app_settings().get(gpu_runtime.SETTING))  # on for an earlier app version
    answer = ask(parent, names[0], again)
    if answer == "never":
        app_settings().set(DISMISSED, gpu_runtime.LEGACY.name)
    elif answer == "load":
        download(parent)
    return answer
