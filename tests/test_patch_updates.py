"""Small updates: the file list of a build (tools/manifest.py), the patch with only the changed files, the
updater choosing it for the running version, and a patch ZIP applied to a copy of the portable folder."""

import importlib.util
import json
import os
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def manifest():
    spec = importlib.util.spec_from_file_location("manifest_tool", ROOT / "tools" / "manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(folder: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return folder


def test_file_list_difference_and_patch(manifest, tmp_path):
    old_dist = _build(tmp_path / "old", {"CLIPassoStudio.exe": b"exe 1", "_internal/torch.dll": b"t" * 1000,
                                         "_internal/app.pyz": b"app 1", "_internal/gone.dll": b"g",
                                         "portable.txt": b"marker"})
    new_dist = _build(tmp_path / "new", {"CLIPassoStudio.exe": b"exe 2", "_internal/torch.dll": b"t" * 1000,
                                         "_internal/app.pyz": b"app 2", "_internal/new.dat": b"n",
                                         "portable.txt": b"marker"})
    old = manifest.build(old_dist, "cpu", "v3.2.0")
    new = manifest.build(new_dist, "CPU", "3.3.0")
    assert old["version"] == "3.2.0" and old["edition"] == "CPU"
    assert "portable.txt" not in new["files"]  # (an installed app must never get the portable marker)
    assert manifest.diff(old, new) == (["CLIPassoStudio.exe", "_internal/app.pyz", "_internal/new.dat"],
                                       ["_internal/gone.dll"])
    info = manifest.make_patch(old, new, new_dist, tmp_path / "patch")
    assert info["ok"] and info["from"] == "3.2.0" and (info["changed"], info["removed"]) == (3, 1)
    assert sorted(p.relative_to(tmp_path / "patch").as_posix() for p in (tmp_path / "patch").rglob("*")
                  if p.is_file()) == ["CLIPassoStudio.exe", "_internal/app.pyz", "_internal/new.dat", "removed.txt"]
    assert (tmp_path / "patch" / "removed.txt").read_text() == "_internal/gone.dll\n"
    assert (tmp_path / "patch-removed.iss").read_text() == 'Type: files; Name: "{app}\\_internal\\gone.dll"\n'
    # a new PyTorch: most of the build changed – full files only
    big = manifest.build(_build(tmp_path / "big", {"CLIPassoStudio.exe": b"exe 2", "_internal/torch.dll": b"u" * 1000}),
                         "CPU", "3.3.0")
    assert not manifest.make_patch(old, big, tmp_path / "big", tmp_path / "patch2")["ok"]

    fake = manifest.fake_previous(new, "3.3.0")
    changed, removed = manifest.diff(fake, new)
    assert "CLIPassoStudio.exe" in changed and len(changed) == 3 and removed == [
        "_internal/left_from_the_previous_version.txt"]


def test_the_command_line(manifest, tmp_path):
    dist = _build(tmp_path / "dist", {"CLIPassoStudio.exe": b"x", "_internal/a.dll": b"a"})
    out = tmp_path / "m.json"
    assert manifest.main(["build", str(dist), "--edition", "GPU", "--version", "3.2.0", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["edition"] == "GPU"
    assert manifest.main(["fake-previous", str(out), "--version", "3.2.0", "--out", str(tmp_path / "f.json")]) == 0


def test_the_updater_takes_the_patch_of_the_running_version():
    from clipasso_studio.gui import updates

    names = ["CLIPassoStudio-CPU-Setup.exe", "CLIPassoStudio-CPU-Portable.exe", "CLIPassoStudio-CPU-Portable.zip",
             "CLIPassoStudio-CPU-Patch-from-3.2.0.exe", "CLIPassoStudio-CPU-Portable-Patch-from-3.2.0.zip",
             "CLIPassoStudio-GPU-Setup.exe", "CLIPassoStudio-GPU-Setup-1.bin",
             "CLIPassoStudio-GPU-Patch-from-3.2.0.exe", "CLIPassoStudio-CPU-manifest.json", "SHA256SUMS-CPU.txt",
             "SHA256SUMS-GPU.txt"]
    release = {"tag": "v3.3.0", "assets": [{"name": n, "url": n, "size": 1} for n in names]}

    def files(edition, mode, current):
        got, sums = updates.update_files(release, edition, mode, current=current)
        assert sums["name"] == f"SHA256SUMS-{edition.upper()}.txt"
        return [a["name"] for a in got]

    assert files("cpu", "installed", "3.2.0") == ["CLIPassoStudio-CPU-Patch-from-3.2.0.exe"]
    assert files("gpu", "installed", "3.2.0") == ["CLIPassoStudio-GPU-Patch-from-3.2.0.exe"]
    assert files("cpu", "portable-zip", "3.2.0") == ["CLIPassoStudio-CPU-Portable-Patch-from-3.2.0.zip"]
    assert files("cpu", "portable", "3.2.0") == ["CLIPassoStudio-CPU-Portable.exe"]  # (always the whole exe)
    assert files("cpu", "installed", "3.1.0") == ["CLIPassoStudio-CPU-Setup.exe"]  # older: the full setup
    assert files("gpu", "installed", "3.1.0") == ["CLIPassoStudio-GPU-Setup.exe", "CLIPassoStudio-GPU-Setup-1.bin"]
    assert updates.can_install(release, "cpu", "installed")


def test_a_patch_zip_updates_a_copy_of_the_portable_folder(tmp_path):
    from clipasso_studio.gui import updates

    old = tmp_path / "apps" / "CLIPasso Studio 3.2.0"
    _build(old, {"CLIPassoStudio.exe": b"old exe", "portable.txt": b"marker", "_internal/torch.dll": b"t" * 500,
                 "_internal/gone.dll": b"g", "_internal/app.pyz": b"app 1"})
    package = tmp_path / "CLIPassoStudio-CPU-Portable-Patch-from-3.2.0.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("CLIPassoStudio/CLIPassoStudio.exe", b"new exe")
        zf.writestr("CLIPassoStudio/_internal/app.pyz", b"app 2")
        zf.writestr("CLIPassoStudio/removed.txt", "_internal/gone.dll\n../../outside.txt\n")
    (tmp_path / "outside.txt").write_text("stays")
    exe = updates.place_portable_zip(str(package), "v3.3.0", app_dir=str(old))
    new = tmp_path / "apps" / "CLIPasso Studio 3.3.0"
    assert exe == str(new / "CLIPassoStudio.exe") and (new / "CLIPassoStudio.exe").read_bytes() == b"new exe"
    assert (new / "_internal" / "app.pyz").read_bytes() == b"app 2"
    assert (new / "_internal" / "torch.dll").stat().st_size == 500  # unchanged files come from the old folder
    assert (new / "portable.txt").is_file() and not (new / "removed.txt").exists()
    assert not (new / "_internal" / "gone.dll").exists() and (tmp_path / "outside.txt").is_file()
    assert (old / "_internal" / "gone.dll").is_file()  # the old version is untouched (deleted later)
    assert not os.path.exists(str(new) + ".partial")


def test_patch_script_brings_the_uninstaller():
    """patch.iss updates the same installation (AppId) and writes an uninstaller with the same code."""
    from clipasso_studio.gui import updates

    patch = (ROOT / "packaging" / "patch.iss").read_bytes()
    installer = (ROOT / "packaging" / "installer.iss").read_bytes()
    assert patch.startswith(b"\xef\xbb\xbf") and installer.startswith(b"\xef\xbb\xbf")
    patch_text, installer_text = patch.decode("utf-8"), installer.decode("utf-8")
    assert "AppId={" + updates.APP_GUID + "_{#Edition}" in patch_text
    assert '#include "uninstall_code.iss"' in patch_text and '#include "uninstall_code.iss"' in installer_text
    for line in installer_text.splitlines():
        if ".DeleteData=" in line:
            assert line in patch_text  # the same question when uninstalling
    assert "OutputBaseFilename=CLIPassoStudio-{#Edition}-Patch-from-{#FromVersion}" in patch_text
    assert updates.patch_name("cpu", "installed", "3.2.0") == "CLIPassoStudio-CPU-Patch-from-3.2.0.exe"
    code = (ROOT / "packaging" / "uninstall_code.iss").read_bytes()
    code.decode("ascii")  # (no BOM needed)
