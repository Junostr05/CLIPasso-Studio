"""The Mac app downloads a model itself (resumable, checked) into the same partial folder Python uses; Python then only
converts it (model_store.convert_downloaded) – for single files and for Hugging Face folders."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch

from clipasso_studio.engine import model_store
from clipasso_studio.engine.errors import UserError


@pytest.fixture
def fake_specs(monkeypatch, tmp_path):
    """Two made-up models: a single file of kind blazeface and a Hugging Face folder (fp16, a prefix kept)."""
    raw = tmp_path / "raw.pt"
    torch.save({"w": torch.arange(4, dtype=torch.float32)}, raw)
    single = model_store.ModelSpec(key="test:single", filename="test/single.pt", urls=("https://example/x",),
                                   download_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                                   download_size=raw.stat().st_size, stored_size_mb=1, bundled=False, kind="blazeface")
    files = (model_store.HFFile("weights/model.safetensors", "model.safetensors", None, True, "visual."),
             model_store.HFFile("config.json", "config.json"))
    hf = model_store._hf_spec("test:hf", "test/hf-model", "org/model", "abc123", files, 1)
    monkeypatch.setitem(model_store.SPECS, single.key, single)
    monkeypatch.setitem(model_store.SPECS, hf.key, hf)
    return single, hf, raw


def _place_single(root: Path, spec, raw: Path) -> Path:
    part = model_store.partial_dir(root) / f"{model_store._safe_name(spec.key)}.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(raw.read_bytes())
    return part


def _place_hf(root: Path, spec, revision: str = "abc123") -> Path:
    from safetensors.torch import save_file

    raw_dir = model_store.partial_dir(root) / model_store._safe_name(spec.key)
    (raw_dir / "weights").mkdir(parents=True)
    (raw_dir / "revision.txt").write_text(revision, encoding="utf-8")
    save_file({"visual.a": torch.ones(3, dtype=torch.float32), "text.b": torch.zeros(2)},
              str(raw_dir / "weights" / "model.safetensors"))
    (raw_dir / "config.json").write_text("{}", encoding="utf-8")
    return raw_dir


def test_convert_downloaded_single_file(fake_specs, tmp_path):
    single, _, raw = fake_specs
    root = tmp_path / "models"
    part = _place_single(root, single, raw)
    path = model_store.convert_downloaded(single.key, root)
    assert path == root / single.filename and path.is_file()
    assert torch.equal(torch.load(path, weights_only=True)["w"], torch.arange(4, dtype=torch.float32))
    assert not part.exists()


def test_convert_downloaded_hf_fp16_prefix(fake_specs, tmp_path):
    from safetensors.torch import load_file

    _, hf, _ = fake_specs
    root = tmp_path / "models"
    raw_dir = _place_hf(root, hf)
    path = model_store.convert_downloaded(hf.key, root)
    assert path == root / hf.filename and path.is_file()  # manifest.json marks a complete installation
    weights = load_file(str(path.parent / "model.safetensors"))
    assert list(weights) == ["visual.a"] and weights["visual.a"].dtype == torch.float16
    assert (path.parent / "config.json").read_text(encoding="utf-8") == "{}"
    assert not raw_dir.exists()


def test_convert_missing_is_not_downloaded(fake_specs, tmp_path):
    single, hf, _ = fake_specs
    for key in (single.key, hf.key):
        with pytest.raises(UserError) as err:
            model_store.convert_downloaded(key, tmp_path / "models")
        assert err.value.code == "not_downloaded"


def test_convert_an_hf_download_of_another_revision_is_not_downloaded(fake_specs, tmp_path):
    _, hf, _ = fake_specs
    _place_hf(tmp_path / "models", hf, revision="old")
    with pytest.raises(UserError) as err:
        model_store.convert_downloaded(hf.key, tmp_path / "models")
    assert err.value.code == "not_downloaded"


def test_convert_a_damaged_download_is_refused(fake_specs, tmp_path):
    single, _, raw = fake_specs
    part = _place_single(tmp_path / "models", single, raw)
    part.write_bytes(part.read_bytes()[:-1] + b"x")
    with pytest.raises(UserError) as err:
        model_store.convert_downloaded(single.key, tmp_path / "models")
    assert err.value.code == "download_failed" and not part.exists()
