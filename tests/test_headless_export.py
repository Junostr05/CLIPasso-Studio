"""The parameter schema and the model list as JSON for the Mac app (``python -m clipasso_studio.headless``)."""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import model_store
from clipasso_studio.headless import export

I18N = Path(__file__).resolve().parent.parent / "clipasso_studio" / "resources" / "i18n"


def _eval(rule: dict, s: dict) -> bool:
    """A reference evaluator of the exported rules (the Mac app implements the same)."""
    op = rule["op"]
    if op == "on":
        return bool(s.get(rule["key"]))
    if op == "off":
        return not s.get(rule["key"])
    if op in ("eq", "ne"):
        same = s.get(rule["key"], rule.get("default")) == rule["value"]
        return same if op == "eq" else not same
    if op == "gt":
        return float(s.get(rule["key"]) or 0) > rule["value"]
    if op == "has":
        return rule["value"] in str(s.get(rule["key"], ""))
    if op == "all":
        return all(_eval(r, s) for r in rule["of"])
    if op == "any":
        return any(_eval(r, s) for r in rule["of"])
    raise AssertionError(op)


def test_schema_has_every_param():
    data = export.export_schema()
    assert data["format"] == 1 and data["methods"] == list(schema.METHODS)
    assert data["default_method"] == schema.DEFAULT_METHOD
    assert data["devices"] == list(schema.param("clipasso", "device").choices)
    for method in schema.METHODS:
        m = data["method"][method]
        assert m["name"] and m["icon"]
        assert m["groups"] == list(schema.METHOD_GROUPS[method])
        assert m["preset_order"] == ["fast", "standard", "quality"]
        assert m["presets"] == schema.METHOD_PRESETS[method]
        assert m["defaults"] == schema.default_settings(method)
        assert [p["key"] for p in m["params"]] == [p.key for p in schema.params_for(method)]
        for p, out in zip(schema.params_for(method), m["params"]):
            assert out["kind"] == p.kind and out["default"] == p.default and out["group"] == p.group
            assert out["min"] == p.minimum and out["max"] == p.maximum and out["step"] == p.step
            assert out["decimals"] == p.decimals and out["choices"] == list(p.choices)
            assert out["advanced"] == p.advanced and out["hidden"] == p.hidden and out["cli"] == p.cli
            assert out["enabled_if"] == (p.enabled_if.to_json() if p.enabled_if else None)
    json.dumps(data)


def test_text_keys_exist_in_both_languages():
    en = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
    de = json.loads((I18N / "de.json").read_text(encoding="utf-8"))
    data = export.export_schema()
    keys = []
    for m in data["method"].values():
        keys += list(m["text"].values()) + list(m["group_text"].values()) + list(m["preset_text"].values())
        for p in m["params"]:
            keys += [p["text"]["label"], p["text"].get("help")] + list(p["text"]["choices"].values())
    keys = [k for k in keys if k]
    assert keys and all(k in en and k in de for k in keys), [k for k in keys if k not in en or k not in de]
    # a method's own text wins over the shared one, like param_text_key of the studio
    swift_width = next(p for p in data["method"]["swiftsketch"]["params"] if p["key"] == "width")
    specific = "param.swiftsketch.width.label"
    assert swift_width["text"]["label"] == (specific if specific in en else "param.width.label")
    assert data["method"]["clipasso"]["params"][0]["text"]["label"] == "param.num_paths.label"


def test_conditions_round_trip():
    data = export.export_schema()
    rng = random.Random(0)
    for method in schema.METHODS:
        params = schema.params_for(method)
        cases = [schema.default_settings(method)]
        for _ in range(200):
            s = schema.default_settings(method)
            for p in params:
                if p.kind == "bool":
                    s[p.key] = rng.random() < 0.5
                elif p.choices and p.kind == "choice":
                    s[p.key] = rng.choice(p.choices)
                elif p.kind in ("int", "float") and p.minimum is not None:
                    s[p.key] = rng.choice((p.minimum, p.default, p.maximum))
            cases.append(s)
        for p, out in zip(params, data["method"][method]["params"]):
            if p.enabled_if is None:
                continue
            for s in cases:
                assert _eval(out["enabled_if"], s) == p.enabled_if(s), (method, p.key)


def test_models_match_store():
    data = export.export_models()
    assert data["format"] == 1 and data["partial_dir"] == ".partial"
    by_key = {m["key"]: m for m in data["models"]}
    assert set(by_key) == set(model_store.SPECS)
    for key, spec in model_store.SPECS.items():
        m = by_key[key]
        assert m["filename"] == spec.filename and m["urls"] == list(spec.urls) and m["kind"] == spec.kind
        assert m["sha256"] == spec.download_sha256 and m["download_size"] == spec.download_size
        assert m["stored_size_mb"] == spec.stored_size_mb
        assert m["mac_bundled"] == (key == "blazeface")
        if spec.kind == "hf":
            assert m["extra"]["repo"] == spec.extra["repo"] and m["extra"]["revision"] == spec.extra["revision"]
            assert [f["remote"] for f in m["extra"]["files"]] == [f.remote for f in spec.extra["files"]]
            first = m["extra"]["files"][0]
            assert set(first) == {"remote", "local", "size", "fp16", "prefix"}
    json.dumps(data)


def test_cli_writes_files_without_torch_or_qt(tmp_path):
    schema_file, models_file = tmp_path / "schema.json", tmp_path / "models.json"
    code = ("import sys; from clipasso_studio.headless.__main__ import main; "
            f"rc = main(['--export-schema', {str(schema_file)!r}, '--export-models', {str(models_file)!r}]); "
            "print(rc, 'torch' in sys.modules, any(m.startswith('PySide6') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=Path(__file__).resolve().parent.parent)
    assert out.stdout.split() == ["0", "False", "False"], out.stderr
    assert json.loads(schema_file.read_text(encoding="utf-8")) == export.export_schema()
    assert json.loads(models_file.read_text(encoding="utf-8")) == export.export_models()


def test_strokes_rule_matches_num_strokes():
    """The Mac app counts the strokes of a job (the gallery's sort) from the exported rule – the same number as
    settings_schema.num_strokes."""
    data = export.export_schema()
    rng = random.Random(0)
    for method in schema.METHODS:
        rule = data["method"][method]["strokes"]
        assert set(rule) == {"key", "fixed", "one_line"}
        for _ in range(200):
            s = schema.default_settings(method)
            for key in ("num_paths", "num_strokes"):
                if key in s:
                    s[key] = rng.randint(1, 256)
            if "one_line" in s:
                s["one_line"] = rng.random() < 0.5
            if rule["fixed"] is not None:
                got = rule["fixed"]
            elif rule["one_line"] and s.get(rule["one_line"]):
                got = 1
            else:
                got = int(s[rule["key"]])
            assert got == schema.num_strokes(s), (method, s)
