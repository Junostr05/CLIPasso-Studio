"""The portable ZIP: recognised by its marker file, updated by unpacking the new version next to the old
folder, which the new version then offers to delete."""

import os
import sys
import types
import zipfile

import pytest

from clipasso_studio.engine.errors import UserError


@pytest.fixture
def frozen_build(monkeypatch):
    monkeypatch.setitem(sys.modules, "clipasso_studio.gui._build_info",
                        types.SimpleNamespace(EDITION="cpu", MODE="installed"))
    import clipasso_studio.gui as gui_pkg

    monkeypatch.setattr(gui_pkg, "_build_info", sys.modules["clipasso_studio.gui._build_info"], raising=False)


def _app(folder):
    os.makedirs(os.path.join(folder, "_internal"))
    for name in ("CLIPassoStudio.exe", "portable.txt"):
        with open(os.path.join(folder, name), "w") as f:
            f.write(name)
    return os.path.join(folder, "CLIPassoStudio.exe")


def test_mode_follows_the_marker(frozen_build, tmp_path):
    from clipasso_studio.gui import updates

    exe = _app(str(tmp_path / "zip"))
    assert updates.build_info(exe) == ("cpu", "portable-zip")
    os.remove(os.path.join(os.path.dirname(exe), "portable.txt"))
    assert updates.build_info(exe) == ("cpu", "installed")


def test_each_mode_gets_its_own_files():
    from clipasso_studio.gui import updates

    names = ["CLIPassoStudio-CPU-Setup.exe", "CLIPassoStudio-CPU-Portable.exe", "CLIPassoStudio-CPU-Portable.zip",
             "CLIPassoStudio-GPU-Setup.exe", "CLIPassoStudio-GPU-Setup-1.bin", "SHA256SUMS-CPU.txt",
             "SHA256SUMS-GPU.txt"]
    release = {"tag": "v9.0.0", "assets": [{"name": n, "url": n, "size": 1} for n in names]}

    def files(edition, mode):
        return [a["name"] for a in updates.update_files(release, edition, mode)[0]]

    assert files("cpu", "installed") == ["CLIPassoStudio-CPU-Setup.exe"]
    assert files("cpu", "portable") == ["CLIPassoStudio-CPU-Portable.exe"]
    assert files("cpu", "portable-zip") == ["CLIPassoStudio-CPU-Portable.zip"]
    assert files("gpu", "installed") == ["CLIPassoStudio-GPU-Setup.exe", "CLIPassoStudio-GPU-Setup-1.bin"]
    assert updates.can_install(release, "cpu", "portable-zip")
    assert not updates.can_install(release, "gpu", "portable-zip")


def _zip(path, extra=()):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("CLIPassoStudio/CLIPassoStudio.exe", b"new exe")
        zf.writestr("CLIPassoStudio/_internal/torch.dll", b"x" * 5000)
        zf.writestr("CLIPassoStudio/portable.txt", b"marker")
        for name, data in extra:
            zf.writestr(name, data)
    return str(path)


def test_unpacked_next_to_the_old_folder(tmp_path):
    from clipasso_studio.gui import updates

    old = tmp_path / "apps" / "CLIPasso Studio 2.4.0"
    _app(str(old))
    package = _zip(tmp_path / "CLIPassoStudio-CPU-Portable.zip", [("CLIPassoStudio/../../evil.txt", b"no")])
    seen = []
    exe = updates.place_portable_zip(package, "v9.0.0", app_dir=str(old), progress=lambda d, t: seen.append((d, t)))
    assert exe == str(tmp_path / "apps" / "CLIPasso Studio 9.0.0" / "CLIPassoStudio.exe")
    assert open(exe, "rb").read() == b"new exe"
    assert (tmp_path / "apps" / "CLIPasso Studio 9.0.0" / "_internal" / "torch.dll").stat().st_size == 5000
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "apps" / "evil.txt").exists()
    assert seen[-1][0] <= seen[-1][1] and seen[-1][1] == 5000 + 7 + 6 + 2
    assert not list((tmp_path / "apps").glob("*.partial"))
    again = updates.place_portable_zip(package, "9.0.0", app_dir=str(old))  # the name is taken
    assert again == str(tmp_path / "apps" / "CLIPasso Studio 9.0.0 (2)" / "CLIPassoStudio.exe")


def test_a_zip_without_the_app_is_refused(tmp_path):
    from clipasso_studio.gui import updates

    with zipfile.ZipFile(tmp_path / "other.zip", "w") as zf:
        zf.writestr("readme.txt", b"hi")
    with pytest.raises(UserError):
        updates.place_portable_zip(str(tmp_path / "other.zip"), "9.0.0", app_dir=str(tmp_path / "app"))


def test_the_new_version_removes_the_old_folder(tmp_path):
    from clipasso_studio.gui import updates

    old, new = str(tmp_path / "CLIPasso Studio 2.4.0"), str(tmp_path / "CLIPasso Studio 9.0.0")
    _app(old)
    new_exe = _app(new)
    program, args = updates.install_command(new_exe, "portable-zip", app_dir=old)
    assert program == new_exe and args == [updates.AFTER_UPDATE_ARG, old]
    assert not updates.is_old_portable_folder(new, current_exe=new_exe)  # never the running version
    assert not updates.is_old_portable_folder(str(tmp_path), current_exe=new_exe)  # not an app folder
    assert updates.is_old_portable_folder(old, current_exe=new_exe)
    assert updates.remove_folder(old) and not os.path.exists(old)
