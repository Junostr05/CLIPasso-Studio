"""Backup & move: one .clipbackup file with the settings, the queue (and its pictures), the gallery and the
models – put back on another computer with other folders."""

import json
import os
import zipfile

import pytest


def _job(out, name):
    job = os.path.join(out, name)
    run = os.path.join(job, f"{name}_run")
    os.makedirs(os.path.join(run, "svg_logs"))
    with open(os.path.join(run, "best_iter.svg"), "w") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M 1 1 L 9 9"/></svg>')
    with open(os.path.join(run, "svg_logs", "svg_iter0.svg"), "w") as f:
        f.write("<svg/>")
    with open(os.path.join(job, "job.json"), "w") as f:
        json.dump({"target": os.path.join(out, "_pasted", f"{name}.png"), "method": "swiftsketch",
                   "best_svg": os.path.join(run, "best_iter.svg"), "best_run": f"{name}_run",
                   "runs": [{"run_name": f"{name}_run", "run_dir": run}]}, f)
    return job


@pytest.fixture
def computer(tmp_path, monkeypatch):
    """A computer: its own app data folder, output folder and model folder (call it again for another one)."""
    from clipasso_studio.gui import app_settings as settings_module

    def make(name):
        root = tmp_path / name
        data, out = root / "data", root / "out"
        out.mkdir(parents=True)
        monkeypatch.setenv("XDG_DATA_HOME", str(data))
        monkeypatch.setenv("LOCALAPPDATA", str(data))
        settings_module._instance = None
        from clipasso_studio.gui.app_settings import app_settings

        app_settings().data["output_dir"] = str(out)
        app_settings().save()
        return root, str(out)

    yield make
    settings_module._instance = None


def test_backup_and_restore_on_another_computer(computer, tmp_path):
    from clipasso_studio import paths
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui import backup
    from clipasso_studio.gui.app_settings import app_settings

    _old, out = computer("old")
    a = _job(out, "camel_a")
    _job(out, "camel_b")
    jobs.write_meta(a, title="Camel", albums=["Animals"])
    os.makedirs(os.path.join(out, "_pasted"))
    pasted = os.path.join(out, "_pasted", "p.png")
    with open(pasted, "wb") as f:
        f.write(b"\x89PNG pasted")
    elsewhere = tmp_path / "photos" / "dog.jpg"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"jpeg of a dog")
    st = app_settings()
    st.data.update(theme="light", language="de", albums=["Animals"], canvas_style="neon", telegram_token="1:secret",
                   queue=[{"target": str(elsewhere), "settings": {"method": "swiftsketch"}},
                          {"target": pasted, "settings": {"method": "clipasso"}}], geometry="old window")
    st.save()
    models = paths.downloaded_models_dir()
    (models / "lama").mkdir(parents=True)
    (models / "lama" / "big-lama.pt").write_bytes(b"x" * 1000)

    sizes = backup.sizes()
    assert sizes["jobs"] == 2 and sizes["queue"] == len(b"jpeg of a dog") + len(b"\x89PNG pasted")
    assert sizes["gallery"] > 0 and backup.models_size() == 1000
    dest = str(tmp_path / backup.default_name())
    seen = []
    manifest = backup.create(dest, include_models=True, progress=lambda d, t: seen.append((d, t)))
    assert manifest["jobs"] == 2 and manifest["queue"] == 2 and manifest["models"] and seen[-1][0] == seen[-1][1]
    with zipfile.ZipFile(dest) as z:
        names = z.namelist()
    assert "gallery/camel_a/meta.json" in names and "gallery/_pasted/p.png" in names
    assert any(n.startswith("queue_inputs/") and n.endswith("dog.jpg") for n in names)  # from outside the output
    assert "models/lama/big-lama.pt" in names
    with zipfile.ZipFile(dest) as z:
        assert "secret" not in z.read("settings.json").decode()  # no tokens in a backup file

    # another computer with other folders; one of the jobs is there already
    _new, new_out = computer("new")
    _job(new_out, "camel_b")
    app_settings().data["geometry"] = "new window"
    m = backup.read_manifest(dest)
    assert m["gallery_names"] == ["_pasted", "camel_a", "camel_b"] and m["has_models"]
    report = backup.restore(dest)
    assert report["settings"] and report["jobs"] == 1 and report["skipped_jobs"] == 1 and report["models"] == 1
    st = app_settings()
    assert st.get("theme") == "light" and st.get("canvas_style") == "neon" and st.get("albums") == ["Animals"]
    assert st.get("output_dir") == new_out and st.get("geometry") == "new window"  # this computer's own
    s = jobs.job_summary(os.path.join(new_out, "camel_a"))
    assert s["title"] == "Camel" and s["albums"] == ["Animals"]
    assert os.path.isfile(s["best_svg"]) and s["best_svg"].startswith(new_out)  # paths found again
    targets = sorted(q["target"] for q in report["queue"])
    assert os.path.join(new_out, "_pasted", "p.png") in targets and os.path.isfile(
        os.path.join(new_out, "_pasted", "p.png"))
    dog = next(t for t in targets if t.endswith("dog.jpg"))
    assert dog.startswith(str(paths.user_data_dir())) and open(dog, "rb").read() == b"jpeg of a dog"
    assert (paths.downloaded_models_dir() / "lama" / "big-lama.pt").stat().st_size == 1000
    # once more: nothing doubles
    again = backup.restore(dest)
    assert again["jobs"] == 0 and again["skipped_jobs"] == 2 and again["models"] == 0
    assert len(again["queue"]) == 2  # (the queue entries are only returned; the app's queue drops doubles)


def test_backup_without_models_and_bad_files(computer, tmp_path):
    from clipasso_studio.gui import backup

    _root, out = computer("one")
    _job(out, "x")
    dest = str(tmp_path / "b.clipbackup")
    backup.create(dest)
    assert not backup.read_manifest(dest)["has_models"]
    with pytest.raises(InterruptedError):
        backup.create(str(tmp_path / "c.clipbackup"), cancel=lambda: True)
    assert not (tmp_path / "c.clipbackup").exists()
    (tmp_path / "junk.clipbackup").write_bytes(b"no zip")
    with pytest.raises(backup.BackupError):
        backup.read_manifest(str(tmp_path / "junk.clipbackup"))
    # a crafted file must not write outside the output folder
    evil = tmp_path / "evil.clipbackup"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": 1, "output_dir": "/x"}))
        z.writestr("settings.json", "{}")
        z.writestr("gallery/../../escaped.txt", "bad")
    backup.restore(str(evil), parts=("gallery",))
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path / "one" / "escaped.txt").exists()
    with zipfile.ZipFile(tmp_path / "new.clipbackup", "w") as z:
        z.writestr("manifest.json", json.dumps({"format": 99}))
    with pytest.raises(backup.BackupError):
        backup.read_manifest(str(tmp_path / "new.clipbackup"))


def test_backup_dialogs(qapp, computer, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from clipasso_studio.gui import backup, backup_ui

    _root, out = computer("ui")
    _job(out, "y")
    dlg = backup_ui.BackupDialog()
    assert not dlg.models.isChecked() and dlg.ok.isEnabled()
    dest = str(tmp_path / "u.clipbackup")
    backup.create(dest)
    restore = backup_ui.BackupDialog(restore_from=dest)
    assert set(restore.parts) == {"settings", "queue", "gallery"}  # no models in this backup
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    (tmp_path / "bad.clipbackup").write_bytes(b"x")
    assert backup_ui.restore_backup(None, str(tmp_path / "bad.clipbackup")) is None
