"""Parameter panel generated from :mod:`clipasso_studio.settings_schema`."""

from __future__ import annotations

import math

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QScrollArea, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ... import settings_schema as schema
from ...engine import model_store
from .. import icons, methods_ui, theme
from ..i18n import i18n, tr
from .common import CollapsibleSection, SegmentedControl, ToggleSwitch, button, label, tool_button

GROUP_ICONS = {
    "basics": "sparkles", "image": "image-plus", "strokes": "pen-tool", "init": "scan", "loss": "gauge",
    "optim": "sliders-horizontal", "augment": "layers", "hardware": "cpu", "diffusion": "wand-sparkles",
    "sds": "wand-sparkles",
}


def param_text_key(method: str, key: str, suffix: str) -> str:
    """i18n key of a parameter text; a method may override the shared text (param.<method>.<key>.*)."""
    specific = f"param.{method}.{key}.{suffix}"
    return specific if i18n.has(specific) else f"param.{key}.{suffix}"


def _choice_text(param: schema.Param, value, method: str = schema.DEFAULT_METHOD) -> str:
    key = param_text_key(method, param.key, f"choice.{value}")
    return tr(key) if i18n.has(key) else str(value)


class ParamField(QWidget):
    changed = Signal(str, object)

    def __init__(self, param: schema.Param, method: str = schema.DEFAULT_METHOD, parent=None):
        super().__init__(parent)
        self.param = param
        self.method = method
        self._value = param.default
        self.start = param.default  # what "reset" goes back to (SceneSketch: its standard preset)
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
        path, _ = QFileDialog.getOpenFileName(self, self._t("label"), "", "SVG (*.svg)")
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
        self.set_value(self.start, emit=True)

    def set_start(self, value) -> None:
        self.start = value
        self._sync_reset()
        self.reset_btn.setToolTip(tr("ui.reset_default", value=str(value)))

    def _sync_reset(self):
        changed = self._value != self.start
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

    def _t(self, suffix: str) -> str:
        return tr(param_text_key(self.method, self.param.key, suffix))

    def retranslate(self):
        p = self.param
        self.title.setText(self._t("label"))
        help_text = self._t("help")
        cli = f"--{p.cli}" if p.cli else ""
        tip = f"<b>{self._t('label')}</b><br>{help_text}"
        if cli:
            tip += f"<br><span style='color:{theme.current().faint}'>{cli}</span>"
        self.info.setPixmap(icons.pixmap("circle-help", theme.current().faint, 13))
        self.info.setToolTip(f"<div style='max-width:320px'>{tip}</div>")
        self.title.setToolTip(self.info.toolTip())
        self.reset_btn.setIcon(icons.icon("rotate-ccw", theme.current().muted))
        self.reset_btn.setToolTip(tr("ui.reset_default", value=str(self.start)))
        if p.kind == "choice":
            for i in range(self.combo.count()):
                self.combo.setItemText(i, _choice_text(p, self.combo.itemData(i), self.method))
        elif p.kind == "flags":
            for c, cb in self.checks.items():
                cb.setText(_choice_text(p, c, self.method))
        elif p.kind == "text":
            ph = param_text_key(self.method, p.key, "placeholder")
            self.edit.setPlaceholderText(tr(ph) if i18n.has(ph) else tr("ui.none_placeholder"))
        elif p.kind == "path":
            self.edit.setPlaceholderText(tr("ui.no_file"))

    def matches(self, query: str) -> bool:
        q = query.lower().strip()
        if not q:
            return True
        p = self.param
        hay = " ".join([p.key, p.cli or "", self._t("label"), self._t("help")]).lower()
        return all(part in hay for part in q.split())


def start_settings(method: str) -> dict:
    """The settings a method starts with (and "Reset" goes back to): the paper's defaults, except for
    SceneSketch, whose paper settings (the full 3 x 9 matrix) take hours even on a GPU – it starts
    with its standard preset (one column); the paper settings are the "Quality" preset."""
    s = schema.default_settings(method)
    if method == "scenesketch":
        s = schema.apply_preset(s, "standard")
    return schema.normalize(s)


class _MethodPage:
    """Fields and sections of one method (only the page of the active method is visible)."""

    def __init__(self, method: str, on_change):
        self.method = method
        self.widget = QWidget()
        lay = QVBoxLayout(self.widget)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.fields: dict[str, ParamField] = {}
        self.sections: dict[str, CollapsibleSection] = {}
        params = schema.params_for(method)
        start = start_settings(method)
        for group in schema.METHOD_GROUPS[method]:
            sec = CollapsibleSection("", GROUP_ICONS.get(group), expanded=group in ("basics", "image"))
            self.sections[group] = sec
            for p in params:
                if p.group != group:
                    continue
                f = ParamField(p, method)
                f.set_start(start.get(p.key, p.default))
                f.changed.connect(on_change)
                self.fields[p.key] = f
                sec.body.addWidget(f)
            lay.addWidget(sec)


class ParamPanel(QWidget):
    settings_changed = Signal(dict)
    method_changed = Signal(str)
    model_needed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._method = schema.DEFAULT_METHOD
        self._per_method = {m: schema.normalize(schema.default_settings(m)) for m in schema.METHODS}
        # SceneSketch's paper settings (the full 3 x 9 matrix) take hours even on a GPU: start with its
        # standard preset (one column); the paper settings are the "Quality" preset
        self._per_method["scenesketch"] = start_settings("scenesketch")
        self._settings = dict(self._per_method[self._method])
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
        self.pages: dict[str, _MethodPage] = {}
        for m in schema.METHODS:
            page = _MethodPage(m, self._field_changed)
            page.widget.setVisible(m == self._method)
            self.inner_lay.addWidget(page.widget)
            self.pages[m] = page
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

    # ------------------------------------------------------------------ method
    @property
    def fields(self) -> dict[str, ParamField]:
        return self.pages[self._method].fields

    @property
    def sections(self) -> dict[str, CollapsibleSection]:
        return self.pages[self._method].sections

    def method(self) -> str:
        return self._method

    def settings_for(self, method: str) -> dict:
        return dict(self._settings) if method == self._method else dict(self._per_method[method])

    def all_settings(self) -> dict[str, dict]:
        return {m: self.settings_for(m) for m in schema.METHODS}

    def set_method(self, method: str) -> None:
        if method != self._method:
            self.set_settings(self._per_method[method])

    def _show_method(self, method: str) -> None:
        self._per_method[self._method] = dict(self._settings)
        self._method = method
        for m, page in self.pages.items():
            page.widget.setVisible(m == method)
        self._filter(self.search.text())
        self.scroll.verticalScrollBar().setValue(0)

    # -------------------------------------------------------------- settings io
    def settings(self) -> dict:
        return dict(self._settings)

    def set_settings(self, settings: dict):
        method = schema.method_of(settings)
        switched = method != self._method
        if switched:
            self._show_method(method)
        self._applying = True
        self._settings = schema.normalize(settings)
        for key, f in self.fields.items():
            f.set_value(self._settings[key])
        self._applying = False
        self._per_method[method] = dict(self._settings)
        self._after_change()
        self._detect_preset()
        if switched:
            self._update_header()
            self.method_changed.emit(method)
        self.settings_changed.emit(self.settings())

    def restore(self, per_method: dict, method: str) -> None:
        """Settings remembered from the last session (one set per method) and the active method."""
        for m in schema.METHODS:
            s = per_method.get(m) if isinstance(per_method, dict) else None
            if isinstance(s, dict):
                try:
                    self._per_method[m] = schema.normalize({**s, "method": m})
                except ValueError:
                    pass
        self._settings = dict(self._per_method[self._method])
        self.set_settings(self._per_method[method if method in schema.METHODS else self._method])

    def apply_preset(self, name: str):
        s = dict(self._settings)
        s.update(schema.METHOD_PRESETS[self._method][name])
        self._preset = name
        self.set_settings(s)
        self.presets.set_current(name)
        self._update_preset_hint()

    def reset_all_fields(self):
        self.set_settings(start_settings(self._method))

    def _field_changed(self, key, value):
        if self._applying:
            return
        self._settings[key] = value
        if self._method == "clipasso":
            if key == "percep_loss" and value != "none" and not self._settings.get("perceptual_weight"):
                self.fields["perceptual_weight"].set_value(1.0, emit=True)
                return
            if key == "clip_text_guide" and value and self._settings.get("text_target") in ("", "none"):
                self.fields["text_target"].set_warning(tr("ui.text_target_needed"))
        self._per_method[self._method] = dict(self._settings)
        self._after_change()
        self._detect_preset()
        self.settings_changed.emit(self.settings())

    def _after_change(self):
        s = self._settings
        for key, f in self.fields.items():
            f.set_enabled_state(schema.is_enabled(f.param, s))
        if self._method == "clipasso":
            self._after_change_clipasso(s)
        elif self._method == "controlsketch":
            self._after_change_controlsketch(s)
        for group, sec in self.sections.items():
            n = sum(1 for p in schema.params_for(self._method)
                    if p.group == group and p.key in self.fields and s[p.key] != self.fields[p.key].start)
            base = tr(f"group.{group}")
            sec.set_title(f"{base}   ·  {tr('ui.n_changed', n=n)}" if n else base)

    def _after_change_clipasso(self, s: dict):
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

    def _after_change_controlsketch(self, s: dict):
        def size_of(keys):
            mb = methods_ui.download_mb(keys)
            return f"{mb / 1000:.1f} GB" if mb >= 1000 else f"{mb:.0f} MB"

        blip_missing = not model_store.is_available("blip")
        if not schema.text_value(s["caption"]):
            self.fields["caption"].set_warning(tr("ui.caption_auto_hint") + (
                " " + tr("ui.model_download_hint", size=size_of(["blip"])) if blip_missing else ""))
        else:
            self.fields["caption"].set_warning(None)
        from ...engine.methods.controlsketch.conditions import DETECTOR_MODELS

        cond_keys = [f"controlnet:{s['condition']}"] + ([DETECTOR_MODELS[s["condition"]]]
                                                        if DETECTOR_MODELS.get(s["condition"]) else [])
        cond_missing = [k for k in cond_keys if not model_store.is_available(k)]
        self.fields["condition"].set_warning(tr("ui.model_download_hint", size=size_of(cond_missing))
                                             if cond_missing else None)
        diffusion = s["use_init_method"] and s["attn_model"] == "diffusion"
        if diffusion and not schema.text_value(s["object_name"]):
            self.fields["object_name"].set_warning(tr("ui.object_name_needed"))
        elif diffusion and not model_store.is_available("sdxl"):
            self.fields["object_name"].set_warning(tr("ui.model_download_hint", size=size_of(["sdxl"])))
        else:
            self.fields["object_name"].set_warning(None)

    def _detect_preset(self):
        for name, values in schema.METHOD_PRESETS[self._method].items():
            if all(self._settings.get(k) == v for k, v in values.items()):
                self._preset = name
                self.presets.set_current(name)
                break
        else:
            self._preset = "custom"
            self.presets.clear_selection()
        self._update_preset_hint()

    def _update_preset_hint(self):
        for key in (f"ui.preset_hint.{self._method}.{self._preset}", f"ui.preset_hint.{self._preset}"):
            if i18n.has(key):
                self.preset_hint.setText(tr(key))
                return
        self.preset_hint.setText("")

    def missing_models(self) -> list[str]:
        return methods_ui.missing_models(self._settings)

    def _filter(self, text: str):
        for group, sec in self.sections.items():
            any_visible = False
            for p in schema.params_for(self._method):
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

    def _update_header(self):
        self.header.setText(f"{tr('ui.parameters')}  ·  {methods_ui.name(self._method)}")

    def retranslate(self):
        self._update_header()
        for key in ("fast", "standard", "quality"):
            self.presets.set_text(key, tr(f"ui.preset.{key}"))
        self.search.setPlaceholderText(tr("ui.search_params"))
        self.reset_all.setText(tr("ui.reset_all"))
        self.import_btn.setToolTip(tr("ui.import_tip"))
        self.export_btn.setToolTip(tr("ui.export_tip"))
        self.cli_btn.setToolTip(tr("ui.copy_cli_tip"))
        for page in self.pages.values():
            for f in page.fields.values():
                f.retranslate()
        self._after_change()
        self._update_preset_hint()
