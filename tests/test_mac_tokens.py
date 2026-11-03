"""The Mac app's design tokens (macos/Sources/StudioCore/Design/Tokens.generated.swift) are made from gui/theme.py
by tools/export_mac_tokens.py – never by hand – and are current."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_mac_tokens_current(qapp, tmp_path):
    spec = importlib.util.spec_from_file_location("export_mac_tokens", ROOT / "tools" / "export_mac_tokens.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.swift() == module.DEFAULT_OUT.read_text(encoding="utf-8"), "run: python tools/export_mac_tokens.py"
    assert module.swift().count("public static let") >= 2 + 15 + 7  # two palettes, spacing, radii
