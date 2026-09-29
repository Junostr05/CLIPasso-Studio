"""Parameter panel generated from :mod:`clipasso_studio.settings_schema`."""

from __future__ import annotations

import math

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QScrollArea, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ... import settings_schema as schema
from ...engine import model_store
from .. import icons, theme
from ..i18n import i18n, tr
from .common import CollapsibleSection, SegmentedControl, ToggleSwitch, button, label, tool_button

GROUP_ICONS = {
    "basics": "sparkles", "image": "image-plus", "strokes": "pen-tool", "init": "scan", "loss": "gauge",
    "optim": "sliders-horizontal", "augment": "layers", "hardware": "cpu",
}


def _choice_text(param: schema.Param, value) -> str:
    key = f"param.{param.key}.choice.{value}"
    return tr(key) if i18n.has(key) else str(value)


class ParamField(QWidget):
    changed = Signal(str, object)

    def __init__(self, param: schema.Param, parent=None):
        super().__init__(parent)
        self.param = param
        self._value = param.default
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = label("", "h3")
        self.info = QLabel()
        self.info.setCursor(Qt.WhatsThisCursor)
        self.reset_btn = QToolButton()
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setAutoRaise(True)
        self.reset_btn.setIconSize(QSize(13, 13))
        self.reset_btn.clicked.connect(self.reset)
        head.addWidget(self.title)
        head.addWidget(self.info)
        head.addStretch(1)
        head.addWidget(self.reset_btn)
        lay.addLayout(head)

        self.control_row = QHBoxLayout()
        self.control_row.setSpacing(8)
        self._build_control(head)
        if self.control_row.count():
            lay.addLayout(self.control_row)
        self.warning = label("", "faint", wrap=True)
        self.warning.setVisible(False)
        lay.addWidget(self.warning)
        self.retranslate()
        self._sync_reset()

    # ------------------------------------------------------------ construction
    def _build_control(self, head: QHBoxLayout):
        p = self.param
        kind = p.kind
        if kind == "bool":
            self.switch = ToggleSwitch()
            self.switch.toggled.connect(lambda v: self._emit(bool(v)))
            head.addWidget(self.switch)
        elif kind in ("int", "float"):
            is_int = kind == "int"
            self.spin = QSpinBox() if is_int else QDoubleSpinBox()
            lo = p.minimum if p.minimum is not None else (0 if is_int else 0.0)
            hi = p.maximum if p.maximum is not None else (10 ** 7 if is_int else 1e6)
            if is_int:
                self.spin.setRange(int(lo), int(hi))
                self.spin.setSingleStep(int(p.step or 1))
            else:
                self.spin.setDecimals(p.decimals)
                self.spin.setRange(float(lo), float(hi))
                self.spin.setSingleStep(float(p.step or 0.1))
            self.spin.setButtonSymbols(QSpinBox.NoButtons)
            self.spin.setAlignment(Qt.AlignRight)
            self.spin.setFixedWidth(84)
            self.slider = None
            span = (hi - lo) / (p.step or 1)
            if span <= 20000 and p.key not in ("seed",):
                self.slider = QSlider(Qt.Horizontal)
                self._slider_scale = 1 if is_int else 1 / float(p.step or 0.01)
                if p.key == "num_paths":  # logarithmic feel for the abstraction level
                    self.slider.setRange(0, 1000)
                else:
                    self.slider.setRange(int(round(lo * self._slider_scale)), int(round(hi * self._slider_scale)))
                self.slider.valueChanged.connect(self._slider_moved)
                self.control_row.addWidget(self.slider, 1)
            else:
                self.control_row.addStretch(1)
            self.control_row.addWidget(self.spin)
            self.spin.valueChanged.connect(self._spin_changed)
        elif kind == "choice":
            self.combo = QComboBox()
            for c in p.choices:
                self.combo.addItem(str(c), c)
            self.combo.currentIndexChanged.connect(lambda i: self._emit(self.combo.itemData(i)))
            self.control_row.addWidget(self.combo, 1)
        elif kind == "text":
            self.edit = QLineEdit()
            self.edit.editingFinished.connect(lambda: self._emit(self.edit.text().strip() or "none"))
            self.control_row.addWidget(self.edit, 1)
        elif kind == "path":
            self.edit = QLineEdit()
            self.edit.setReadOnly(True)
            browse = QToolButton()
            browse.setIcon(icons.icon("folder-open", theme.current().muted))
            browse.setCursor(Qt.PointingHandCursor)
            browse.clicked.connect(self._browse)
            clear = QToolButton()
            clear.setIcon(icons.icon("x", theme.current().muted))
            clear.setCursor(Qt.PointingHandCursor)
            clear.clicked.connect(lambda: self._emit("none"))
            self.control_row.addWidget(self.edit, 1)
            self.control_row.addWidget(browse)
            self.control_row.addWidget(clear)
        elif kind == "layers":
            self.layers_box = QWidget()
            self.layers_grid = QGridLayout(self.layers_box)
            self.layers_grid.setContentsMargins(0, 0, 0, 0)
            self.layers_grid.setHorizontalSpacing(4)
            self.layers_grid.setVerticalSpacing(2)
            self.layer_sliders: list[QSlider] = []
            self.layer_labels: list[QLabel] = []
            self.control_row.addWidget(self.layers_box, 1)
            self._build_layers(5)
        elif kind == "flags":
            self.checks = {}
            for c in p.choices:
                cb = QCheckBox()
                cb.toggled.connect(self._flags_changed)
                self.checks[c] = cb
                self.control_row.addWidget(cb)
            self.control_row.addStretch(1)

    def _build_layers(self, n: int):
        for s in self.layer_sliders:
            s.setParent(None)
        for lbl in self.layer_labels:
            lbl.setParent(None)
        self.layer_sliders, self.layer_labels = [], []
        per_row = 6
        for i in range(n):
            s = QSlider(Qt.Vertical)
            s.setRange(0, 100)  # 0 .. 10.0
            s.setFixedHeight(54)
            s.valueChanged.connect(self._layers_changed)
            name = QLabel(f"{'L' if n == 5 else 'B'}{i}")
            name.setProperty("role", "faint")
            name.setAlignment(Qt.AlignCenter)
            row = (i // per_row) * 2
            col = i % per_row
            self.layers_grid.addWidget(s, row, col, Qt.AlignHCenter)
            self.layers_grid.addWidget(name, row + 1, col, Qt.AlignHCenter)
            self.layer_sliders.append(s)
            self.layer_labels.append(name)

    # ---------------------------------------------------------------- behaviour
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, tr(f"param.{self.param.key}.label"), "", "SVG (*.svg)")
        if path:
            self._emit(path)

    def _slider_to_value(self, pos: int):
        p = self.param
        if p.key == "num_paths":
            lo, hi = math.log(p.minimum), math.log(p.maximum)
            return int(round(math.exp(lo + (hi - lo) * pos / 1000)))
        v = pos / self._slider_scale
        return int(round(v)) if p.kind == "int" else v

    def _value_to_slider(self, value) -> int:
        p = self.param
        if p.key == "num_paths":
            lo, hi = math.log(p.minimum), math.log(p.maximum)
            return int(round((math.log(max(value, 1)) - lo) / (hi - lo) * 1000))
        return int(round(value * self._slider_scale))

    def _slider_moved(self, pos: int):
        if self._updating:
            return
        value = self._slider_to_value(pos)
        self._updating = True
        self.spin.setValue(value)
        self._updating = False
        self._emit(value, update_widgets=False)

    def _spin_changed(self, value):
        if self._updating:
            return
        if self.slider is not None:
            self._updating = True
            self.slider.setValue(self._value_to_slider(value))
            self._updating = False
        self._emit(value, update_widgets=False)

    def _flags_changed(self):
        if self._updating:
            return
        parts = [c for c, cb in self.checks.items() if cb.isChecked()]
        self._emit("_".join(parts) or "none")

    def _layers_changed(self):
        if self._updating:
            return
        weights = [s.value() / 10 for s in self.layer_sliders]
        self._emit(schema.format_layer_weights(weights))

    def _emit(self, value, update_widgets: bool = True):
        try:
            value = schema.coerce(self.param, value)
        except ValueError:
            return
        if update_widgets:
            self.set_value(value, emit=False)
        else:
            self._value = value
            self._sync_reset()
            self._refresh_layer_labels()
        self.changed.emit(self.param.key, value)

    def set_layer_count(self, n: int):
        if self.param.kind != "layers" or len(self.layer_sliders) == n:
            return
        weights = schema.parse_layer_weights(self._value)
        self._build_layers(n)
        weights = (weights + [0.0] * n)[:n] if len(weights) != n else weights
        self.set_value(schema.format_layer_weights(weights), emit=True)

    def set_value(self, value, emit: bool = False):
        p = self.param
        self._value = value
        self._updating = True
        try:
            if p.kind == "bool":
                self.switch.setChecked(bool(value))
            elif p.kind in ("int", "float"):
                self.spin.setValue(value)
                if self.slider is not None:
                    self.slider.setValue(self._value_to_slider(value))
            elif p.kind == "choice":
                idx = self.combo.findData(value)
                if idx >= 0:
                    self.combo.setCurrentIndex(idx)
            elif p.kind == "text":
                self.edit.setText("" if value in (None, "none") else str(value))
            elif p.kind == "path":
                self.edit.setText("" if value in (None, "none") else str(value))
                self.edit.setToolTip(self.edit.text())
            elif p.kind == "layers":
                weights = schema.parse_layer_weights(value)
                if len(weights) != len(self.layer_sliders) and len(weights) in (5, 12):
                    self._build_layers(len(weights))
                for s, w in zip(self.layer_sliders, weights):
                    s.setValue(int(round(w * 10)))
                self._refresh_layer_labels()
            elif p.kind == "flags":
                parts = str(value).split("_")
                for c, cb in self.checks.items():
                    cb.setChecked(c in parts)
        finally:
            self._updating = False
        self._sync_reset()
        if emit:
            self.changed.emit(p.key, value)

    def _refresh_layer_labels(self):
        if self.param.kind != "layers":
            return
        n = len(self.layer_sliders)
        for i, (s, lbl) in enumerate(zip(self.layer_sliders, self.layer_labels)):
            prefix = "L" if n == 5 else "B"
            lbl.setText(f"{prefix}{i}\n{s.value() / 10:g}")

    def value(self):
        return self._value

    def reset(self):
        self.set_value(self.param.default, emit=True)

    def _sync_reset(self):
        changed = self._value != self.param.default
        self.reset_btn.setVisible(changed)
        self.title.setStyleSheet(f"color: {theme.current().accent_hover};" if changed else "")

    def set_enabled_state(self, enabled: bool):
        for w in self.findChildren(QWidget):
            if w not in (self.info,):
                w.setEnabled(enabled)
        self.title.setEnabled(enabled)

    def set_warning(self, text: str | None):
        self.warning.setVisible(bool(text))
        self.warning.setText(text or "")

    def retranslate(self):
        p = self.param
        self.title.setText(tr(f"param.{p.key}.label"))
        help_text = tr(f"param.{p.key}.help")
        cli = f"--{p.cli}" if p.cli else ""
        tip = f"<b>{tr(f'param.{p.key}.label')}</b><br>{help_text}"
        if cli:
            tip += f"<br><span style='color:{theme.current().faint}'>{cli}</span>"
        self.info.setPixmap(icons.pixmap("circle-help", theme.current().faint, 13))
        self.info.setToolTip(f"<div style='max-width:320px'>{tip}</div>")
        self.title.setToolTip(self.info.toolTip())
        self.reset_btn.setIcon(icons.icon("rotate-ccw", theme.current().muted))
        self.reset_btn.setToolTip(tr("ui.reset_default", value=str(p.default)))
        if p.kind == "choice":
            for i in range(self.combo.count()):
                self.combo.setItemText(i, _choice_text(p, self.combo.itemData(i)))
        elif p.kind == "flags":
            for c, cb in self.checks.items():
                cb.setText(_choice_text(p, c))
        elif p.kind == "text":
            self.edit.setPlaceholderText(tr("ui.none_placeholder"))
        elif p.kind == "path":
            self.edit.setPlaceholderText(tr("ui.no_file"))

    def matches(self, query: str) -> bool:
        q = query.lower().strip()
        if not q:
            return True
        p = self.param
        hay = " ".join([p.key, p.cli or "", tr(f"param.{p.key}.label"), tr(f"param.{p.key}.help")]).lower()
        return all(part in hay for part in q.split())


class ParamPanel(QWidget):
    settings_changed = Signal(dict)
    model_needed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = schema.default_settings()
        self._preset = "standard"
        self._applying = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self.header = label("", "h2")
        outer.addWidget(self.header)
        self.presets = SegmentedControl([("fast", ""), ("standard", ""), ("quality", "")])
        self.presets.changed.connect(self.apply_preset)
        outer.addWidget(self.presets)
        self.preset_hint = label("", "faint", wrap=True)
        outer.addWidget(self.preset_hint)

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", theme.current().faint), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        outer.addWidget(self.search)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.inner_lay = QVBoxLayout(inner)
        self.inner_lay.setContentsMargins(0, 0, 8, 0)
        self.inner_lay.setSpacing(2)
        self.fields: dict[str, ParamField] = {}
        self.sections: dict[str, CollapsibleSection] = {}
        for group in schema.GROUPS:
            sec = CollapsibleSection("", GROUP_ICONS.get(group), expanded=group in ("basics", "image"))
            self.sections[group] = sec
            for p in schema.PARAMS:
                if p.group != group:
                    continue
                f = ParamField(p)
                f.changed.connect(self._field_changed)
                self.fields[p.key] = f
                sec.body.addWidget(f)
            self.inner_lay.addWidget(sec)
        self.inner_lay.addStretch(1)
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.reset_all = button("", "rotate-ccw", "ghost")
        self.reset_all.clicked.connect(self.reset_all_fields)
        self.import_btn = tool_button("folder-open", "", 16)
        self.export_btn = tool_button("file-down", "", 16)
        self.cli_btn = tool_button("copy", "", 16)
        row.addWidget(self.reset_all)
        row.addStretch(1)
        for b in (self.import_btn, self.export_btn, self.cli_btn):
            row.addWidget(b)
        outer.addLayout(row)

        self.set_settings(self._settings)
        self.retranslate()
        i18n.language_changed.connect(lambda _: self.retranslate())

    # -------------------------------------------------------------- settings io
    def settings(self) -> dict:
        return dict(self._settings)

    def set_settings(self, settings: dict):
        self._applying = True
        self._settings = schema.normalize(settings)
        for key, f in self.fields.items():
            f.set_value(self._settings[key])
        self._applying = False
        self._after_change()
        self._detect_preset()

    def apply_preset(self, name: str):
        s = dict(self._settings)
        s.update(schema.PRESETS[name])
        self._preset = name
        self.set_settings(s)
        self.presets.set_current(name)
        self._update_preset_hint()
        self.settings_changed.emit(self.settings())

    def reset_all_fields(self):
        self.set_settings(schema.default_settings())
        self.settings_changed.emit(self.settings())

    def _field_changed(self, key, value):
        if self._applying:
            return
        self._settings[key] = value
        if key == "percep_loss" and value != "none" and not self._settings.get("perceptual_weight"):
            self.fields["perceptual_weight"].set_value(1.0, emit=True)
            return
        if key == "clip_text_guide" and value and self._settings.get("text_target") in ("", "none"):
            self.fields["text_target"].set_warning(tr("ui.text_target_needed"))
        self._after_change()
        self._detect_preset()
        self.settings_changed.emit(self.settings())

    def _after_change(self):
        s = self._settings
        for key, f in self.fields.items():
            f.set_enabled_state(schema.is_enabled(f.param, s))
        self.fields["clip_conv_layer_weights"].set_layer_count(schema.num_conv_layers(s["clip_model_name"]))
        self._settings["clip_conv_layer_weights"] = self.fields["clip_conv_layer_weights"].value()
        # model availability hints
        for key in ("clip_model_name", "saliency_clip_model"):
            spec = model_store.clip_key(s[key])
            needed = key == "clip_model_name" or (s["attention_init"] and s["saliency_model"] == "clip")
            if needed and not model_store.is_available(spec):
                self.fields[key].set_warning(tr("ui.model_missing_hint"))
            else:
                self.fields[key].set_warning(None)
        if not (s["clip_text_guide"] and s.get("text_target") in ("", "none")):
            self.fields["text_target"].set_warning(None)
        for group, sec in self.sections.items():
            n = sum(1 for p in schema.PARAMS if p.group == group and s[p.key] != p.default)
            base = tr(f"group.{group}")
            sec.set_title(f"{base}   ·  {tr('ui.n_changed', n=n)}" if n else base)

    def _detect_preset(self):
        for name, values in schema.PRESETS.items():
            if all(self._settings.get(k) == v for k, v in values.items()):
                self._preset = name
                self.presets.set_current(name)
                break
        else:
            self._preset = "custom"
            self.presets.clear_selection()
        self._update_preset_hint()

    def _update_preset_hint(self):
        key = f"ui.preset_hint.{self._preset}"
        self.preset_hint.setText(tr(key) if i18n.has(key) else "")

    def missing_models(self) -> list[str]:
        s = self._settings
        needed = {model_store.clip_key(s["clip_model_name"])}
        if s["attention_init"]:
            needed.add(model_store.clip_key(s["saliency_clip_model"]) if s["saliency_model"] == "clip" else "dino")
        if s["train_with_clip"] or s["clip_text_guide"]:
            needed.add(model_store.clip_key("ViT-B/32"))
        if s["percep_loss"] == "LPIPS":
            needed.add("vgg16")
        needed.add("u2net")
        return sorted(k for k in needed if not model_store.is_available(k))

    def _filter(self, text: str):
        for group, sec in self.sections.items():
            any_visible = False
            for p in schema.PARAMS:
                if p.group != group:
                    continue
                vis = self.fields[p.key].matches(text)
                self.fields[p.key].setVisible(vis)
                any_visible |= vis
            sec.setVisible(any_visible)
            if text.strip() and any_visible:
                sec.set_expanded(True)

    def expand_all(self, expanded: bool = True):
        for sec in self.sections.values():
            sec.set_expanded(expanded)

    def retranslate(self):
        self.header.setText(tr("ui.parameters"))
        for key in ("fast", "standard", "quality"):
            self.presets.set_text(key, tr(f"ui.preset.{key}"))
        self.search.setPlaceholderText(tr("ui.search_params"))
        self.reset_all.setText(tr("ui.reset_all"))
        self.import_btn.setToolTip(tr("ui.import_tip"))
        self.export_btn.setToolTip(tr("ui.export_tip"))
        self.cli_btn.setToolTip(tr("ui.copy_cli_tip"))
        for f in self.fields.values():
            f.retranslate()
        self._after_change()
        self._update_preset_hint()
