"""Settings → Phone & messages: the remote page in the home network (address and QR code) and the Telegram bot."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from . import remote, telegram
from .app_settings import app_settings
from .dialogs import run_in_thread
from .i18n import tr
from .widgets.common import Card, SegmentedControl, ToggleSwitch, button, label


def _row(lbl, widget):
    r = QHBoxLayout()
    r.addWidget(lbl)
    r.addStretch(1)
    r.addWidget(widget)
    return r


class PhoneCard(Card):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.link = None  # PhoneLink of the main window
        self._connecting = False
        self._cancel = False
        st = app_settings()
        self.title = label("", "h2")
        self.desc = label("", "faint", wrap=True)
        self.body.addWidget(self.title)
        self.body.addWidget(self.desc)
        # ---- remote page
        self.remote_label = label("", None)
        self.remote_on = ToggleSwitch()
        self.remote_on.setChecked(bool(st.get("remote_on")))
        self.remote_on.toggled.connect(self._remote_toggled)
        self.body.addLayout(_row(self.remote_label, self.remote_on))
        self.remote_box = QWidget()
        rb = QHBoxLayout(self.remote_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(14)
        self.qr = QLabel()
        self.qr.setFixedSize(150, 150)
        self.qr.setScaledContents(True)
        rb.addWidget(self.qr, 0, Qt.AlignTop)
        info = QWidget()
        il = QVBoxLayout(info)
        il.setContentsMargins(0, 0, 0, 0)
        self.url = label("", None, wrap=True)
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.remote_hint = label("", "faint", wrap=True)
        self.port_label = label("", None)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(st.get("remote_port", remote.DEFAULT_PORT) or remote.DEFAULT_PORT))
        self.port.editingFinished.connect(self._port_changed)
        self.new_code = button("", "refresh-cw", "ghost", size="sm")
        self.new_code.clicked.connect(self.new_access_code)
        # Tailscale: phones of the user's tailnet (also away from home), with a QR code of the tailnet address
        self.ts_box = QWidget()
        tb = QVBoxLayout(self.ts_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(6)
        self.ts_label = label("", None)
        self.ts_on = ToggleSwitch()
        self.ts_on.setChecked(bool(st.get("remote_tailscale")))
        self.ts_on.toggled.connect(self._tailscale_toggled)
        tb.addLayout(_row(self.ts_label, self.ts_on))
        self.net = SegmentedControl([("lan", ""), ("tailscale", "")])
        self.net.set_current("lan")
        self.net.changed.connect(lambda _k: self.refresh())
        tb.addWidget(self.net, 0, Qt.AlignLeft)
        self.ts_hint = label("", "faint", wrap=True)
        tb.addWidget(self.ts_hint)
        # the fixed address (bookmark / home screen) and the PIN for when the phone no longer knows the QR code
        self.fixed = label("", None, wrap=True)
        self.fixed.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.fixed.setOpenExternalLinks(True)
        self.pin_label = label("", None)
        self.pin_edit = QLineEdit()
        self.pin_edit.setMaxLength(remote.PIN_DIGITS)
        self.pin_edit.setFixedWidth(110)
        self.pin_edit.setAlignment(Qt.AlignCenter)
        from PySide6.QtCore import QRegularExpression
        from PySide6.QtGui import QRegularExpressionValidator

        self.pin_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}")))
        self.pin_edit.editingFinished.connect(self._pin_changed)
        self.new_pin_btn = button("", "refresh-cw", "ghost", size="sm")
        self.new_pin_btn.clicked.connect(self.new_pin)
        pin_row = QHBoxLayout()
        pin_row.addWidget(self.pin_label)
        pin_row.addStretch(1)
        pin_row.addWidget(self.pin_edit)
        pin_row.addWidget(self.new_pin_btn)
        self.pin_hint = label("", "faint", wrap=True)
        il.addWidget(self.fixed)
        il.addLayout(pin_row)
        il.addWidget(self.pin_hint)
        il.addWidget(self.url)
        il.addWidget(self.ts_box)
        il.addLayout(_row(self.port_label, self.port))
        il.addWidget(self.new_code, 0, Qt.AlignLeft)
        il.addWidget(self.remote_hint)
        il.addStretch(1)
        rb.addWidget(info, 1)
        self.body.addWidget(self.remote_box)
        self.remote_error = label("", "badge-warning", wrap=True)
        self.body.addWidget(self.remote_error)
        # ---- Telegram
        self.tg_label = label("", None)
        self.tg_on = ToggleSwitch()
        self.tg_on.setChecked(bool(st.get("telegram_on")))
        self.tg_on.toggled.connect(lambda v: (app_settings().set("telegram_on", bool(v)), self.refresh()))
        self.body.addLayout(_row(self.tg_label, self.tg_on))
        self.tg_box = QWidget()
        tl = QVBoxLayout(self.tg_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        self.tg_help = label("", "faint", wrap=True)
        self.tg_help.setOpenExternalLinks(True)
        tl.addWidget(self.tg_help)
        r = QHBoxLayout()
        self.token = QLineEdit(st.get("telegram_token") or "")
        self.token.setEchoMode(QLineEdit.Password)
        self.token.editingFinished.connect(self._token_changed)
        self.connect_btn = button("", "zap")
        self.connect_btn.clicked.connect(self.connect_telegram)
        r.addWidget(self.token, 1)
        r.addWidget(self.connect_btn)
        tl.addLayout(r)
        self.tg_status = label("", "muted", wrap=True)
        tl.addWidget(self.tg_status)
        checks = QHBoxLayout()
        self.tg_checks = {}
        for key in ("done", "failed", "photo"):
            box = QCheckBox()
            box.setChecked(bool(st.get(f"telegram_{key}", True)))
            box.toggled.connect(lambda v, k=key: app_settings().set(f"telegram_{k}", bool(v)))
            checks.addWidget(box)
            self.tg_checks[key] = box
        checks.addStretch(1)
        tl.addLayout(checks)
        self.test_btn = button("", None, "ghost", size="sm")
        self.test_btn.clicked.connect(self.send_test)
        tl.addWidget(self.test_btn, 0, Qt.AlignLeft)
        self.body.addWidget(self.tg_box)
        self.retranslate()

    def set_link(self, link) -> None:
        self.link = link
        self.refresh()

    # ------------------------------------------------------------------ remote
    def _remote_toggled(self, on: bool):
        app_settings().set("remote_on", bool(on))
        if self.link is not None:
            self.link.apply_settings()
        self.refresh()

    def _tailscale_toggled(self, on: bool):
        app_settings().set("remote_tailscale", bool(on))
        self.net.set_current("tailscale" if on else "lan")
        self.refresh()

    def _pin_changed(self):
        text = self.pin_edit.text().strip()
        if remote.valid_pin(text):
            app_settings().set("remote_pin", text)
        else:
            self.pin_edit.setText(remote.pin())  # (not six digits: the PIN stays)

    def new_pin(self) -> str:
        p = remote.new_pin()
        app_settings().set("remote_pin", p)
        self.pin_edit.setText(p)
        return p

    def _port_changed(self):
        if self.port.value() != int(app_settings().get("remote_port", remote.DEFAULT_PORT) or 0):
            app_settings().set("remote_port", self.port.value())
            if self.link is not None:
                self.link.apply_settings()
            self.refresh()

    def new_access_code(self):
        """A new code: phones that had the old one need the new QR code."""
        app_settings().set("remote_token", remote.new_token())
        self.refresh()

    # ------------------------------------------------------------------ Telegram
    def _token_changed(self):
        token = self.token.text().strip()
        st = app_settings()
        if token != (st.get("telegram_token") or ""):
            st.data.update(telegram_chat="", telegram_bot="")
            st.set("telegram_token", token)
            self.refresh()

    def connect_telegram(self):
        if self._connecting:
            self._cancel = True
            return
        self._token_changed()
        token = self.token.text().strip()
        if not telegram.valid_token(token):
            self.tg_status.setText(tr("ui.telegram.bad_token"))
            return
        self._connecting, self._cancel = True, False
        self.connect_btn.setText(tr("ui.cancel"))
        self.tg_status.setText(tr("ui.telegram.checking"))

        def work(progress=None):
            name = telegram.bot_name(token)
            progress(1, 2)
            self._bot = name
            return name, telegram.find_chat(token, cancel=lambda: self._cancel)

        def prog(a, b):
            if a == 1:
                self.tg_status.setText(tr("ui.telegram.send_start", bot=f"@{getattr(self, '_bot', '')}",
                                          seconds=telegram.CONNECT_SECONDS))

        def done(result):
            self._connecting = False
            name, chat = result
            if chat is None:
                self.tg_status.setText(tr("ui.telegram.no_start"))
            else:
                st = app_settings()
                st.data.update(telegram_chat=chat[0], telegram_bot=name, telegram_on=True)
                st.save()
                self.tg_on.blockSignals(True)
                self.tg_on.setChecked(True)
                self.tg_on.blockSignals(False)
                if self.link is not None:
                    self.link.notifier.message(tr("ui.telegram.hello"))
            self.refresh()

        def failed(msg):
            self._connecting = False
            self.refresh()
            self.tg_status.setText(tr("ui.telegram.failed", error=msg))

        run_in_thread(self, work, on_progress=prog, on_done=done, on_error=failed)

    def send_test(self):
        if self.link is not None and telegram.configured():
            self.link.notifier.message(tr("ui.telegram.test"))
            self.tg_status.setText(tr("ui.telegram.test_sent"))

    # ------------------------------------------------------------------ texts and state
    def refresh(self):
        st = app_settings()
        on = bool(st.get("remote_on"))
        running = self.link is not None and self.link.running()
        self.remote_box.setVisible(on and running)
        error = self.link.error if self.link is not None else ""
        self.remote_error.setText(error)
        self.remote_error.setVisible(on and bool(error))
        if on and running:
            ts_ip = remote.tailscale_address()
            ts_on = bool(st.get("remote_tailscale"))
            self.ts_box.setVisible(bool(ts_ip) or ts_on)  # (only where Tailscale runs, or was switched on)
            self.net.setVisible(ts_on and bool(ts_ip))
            self.ts_hint.setVisible(ts_on)
            self.ts_hint.setText(tr("ui.phone.tailscale_hint") if ts_ip else tr("ui.phone.tailscale_missing"))
            use_ts = ts_on and bool(ts_ip) and self.net.current() == "tailscale"
            address = remote.url(self.link.server.port, ts_ip if use_ts else None)
            fixed = address.split("?", 1)[0]  # the same address without the access code: then the PIN
            self.fixed.setText(tr("ui.phone.fixed", url=f"<a href='{fixed}'>{fixed}</a>"))
            if not self.pin_edit.hasFocus():
                self.pin_edit.setText(remote.pin())
            self.url.setText(f"<span style='font-size:small'>{tr('ui.phone.qr_link')} "
                             f"<a href='{address}'>{address}</a></span>")
            try:
                pm = QPixmap()
                pm.loadFromData(remote.qr_png(address))
                self.qr.setPixmap(pm)
            except Exception:  # (no QR code: the address is enough)
                self.qr.clear()
        self.tg_box.setVisible(bool(st.get("telegram_on")) or self._connecting)
        if not self._connecting:
            self.connect_btn.setText(tr("ui.telegram.connect"))
            bot, chat = st.get("telegram_bot") or "", st.get("telegram_chat") or ""
            self.tg_status.setText(tr("ui.telegram.connected", bot=f"@{bot}") if bot and chat
                                   else tr("ui.telegram.not_connected"))
        self.test_btn.setEnabled(telegram.configured())

    def retranslate(self):
        self.title.setText(tr("ui.phone.title"))
        self.desc.setText(tr("ui.phone.desc"))
        self.remote_label.setText(tr("ui.phone.remote"))
        self.remote_hint.setText(tr("ui.phone.remote_hint"))
        self.port_label.setText(tr("ui.phone.port"))
        self.new_code.setText(tr("ui.phone.new_code"))
        self.new_code.setToolTip(tr("ui.phone.new_code_tip"))
        self.pin_label.setText(tr("ui.phone.pin"))
        self.pin_edit.setToolTip(tr("ui.phone.pin_tip"))
        self.new_pin_btn.setText(tr("ui.phone.new_pin"))
        self.pin_hint.setText(tr("ui.phone.pin_hint"))
        self.ts_label.setText(tr("ui.phone.tailscale"))
        self.ts_label.setToolTip(tr("ui.phone.tailscale_tip"))
        self.net.set_text("lan", tr("ui.phone.net_lan"))
        self.net.set_text("tailscale", "Tailscale")
        self.tg_label.setText(tr("ui.telegram.label"))
        self.tg_help.setText(tr("ui.telegram.help"))
        self.token.setPlaceholderText(tr("ui.telegram.token"))
        for key, box in self.tg_checks.items():
            box.setText(tr(f"ui.telegram.on_{key}"))
        self.test_btn.setText(tr("ui.telegram.test_button"))
        self.refresh()
