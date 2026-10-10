"""Updates: is a newer CLIPasso Studio release available on GitHub – and installing it.

The check only asks the GitHub API for the latest release (no data is sent); pre-releases (betas) only
count when "Also offer beta versions" is on – a setting of the Windows app –, and offline or on any error it
simply finds nothing. *Install* downloads the files of this
edition (resumable), checks them against the release's SHA256SUMS file and then runs the installer
silently (installed app; it starts the new version afterwards) or starts the new portable exe.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

from .. import __version__, paths
from ..engine.errors import UserError
from ..fileops import ensure_space, folder_size

RELEASES_API = "https://api.github.com/repos/Junostr05/CLIPasso-Studio/releases/latest"
RELEASES_LIST = "https://api.github.com/repos/Junostr05/CLIPasso-Studio/releases?per_page=30"  # with the betas
RELEASES_PAGE = "https://github.com/Junostr05/CLIPasso-Studio/releases/latest"

_STAGES = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}  # a final release ranks above all of them


def parse_version(text: str) -> tuple[int, ...]:
    """"v2.1.0" / "2.1.0b1" / "v2.1.0-beta.1" -> comparable tuple."""
    m = re.match(r"\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?(alpha|beta|rc|a|b)\.?(\d*))?", text or "", re.I)
    if not m:
        return (0,)
    major, minor, patch = (int(x or 0) for x in m.group(1, 2, 3))
    stage = _STAGES.get((m.group(4) or "").lower(), 3)
    return (major, minor, patch, stage, int(m.group(5) or 0))


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def beta_allowed() -> bool:
    """Betas are built for Windows only (there is no other build): elsewhere the app offers none."""
    return sys.platform == "win32"


def beta_channel() -> bool:
    """Whether betas are offered: the setting "Also offer beta versions" (PC or phone), on Windows."""
    from .app_settings import app_settings

    return beta_allowed() and bool(app_settings().get("beta_updates"))


def _release(data, betas: bool) -> dict | None:
    if not isinstance(data, dict) or data.get("draft") or not data.get("tag_name"):
        return None
    if data.get("prerelease") and not betas:
        return None
    assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""), "size": int(a.get("size") or 0)}
              for a in data.get("assets") or [] if isinstance(a, dict)]
    return {"tag": data["tag_name"], "url": data.get("html_url") or RELEASES_PAGE, "name": data.get("name") or "",
            "body": str(data.get("body") or ""), "assets": assets, "prerelease": bool(data.get("prerelease"))}


def latest_release(url: str = RELEASES_API, timeout: float = 5.0, betas: bool = False) -> dict | None:
    """The newest release: the latest final one, or with ``betas`` the newest of all (a list of releases;
    4.0.0 ranks above 4.0.0b3)."""
    req = urllib.request.Request(url, headers={"User-Agent": "CLIPassoStudio",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    if not betas:
        return _release(data, False)
    found = [r for r in (_release(d, True) for d in (data if isinstance(data, list) else [data])) if r]
    return max(found, key=lambda r: parse_version(r["tag"]), default=None)


def _channel(url: str | None, betas: bool | None) -> tuple[str, bool]:
    betas = beta_channel() if betas is None else betas
    return url or (RELEASES_LIST if betas else RELEASES_API), betas


def check(progress=None, url: str | None = None, current: str = __version__, betas: bool | None = None) -> str:
    """For ``run_in_thread``: the newer release as JSON, or "" (up to date, offline, error). ``betas``: also
    pre-releases (None: as set)."""
    url, betas = _channel(url, betas)
    try:
        release = latest_release(url, betas=betas)
    except Exception:
        return ""
    if release and is_newer(release["tag"], current):
        return json.dumps(release)
    return ""


def check_now(progress=None, url: str | None = None, current: str = __version__, betas: bool | None = None) -> str:
    """For "Check for updates now" (``run_in_thread``): JSON ``{"status": "newer" | "current" | "error",
    "release": …}`` – unlike :func:`check` it tells "up to date" from "offline"."""
    url, betas = _channel(url, betas)
    try:
        release = latest_release(url, betas=betas)
    except Exception as exc:  # offline, rate limit …
        return json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
    if release and is_newer(release["tag"], current):
        return json.dumps({"status": "newer", "release": release})
    return json.dumps({"status": "current"})


WHATS_NEW = "whats_new_{lang}.md"  # what is new in this version, shown at the first start after an update


def whats_new_text(lang: str) -> str:
    for code in (lang, "en"):
        path = paths.resource(WHATS_NEW.format(lang=code))
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def updated_since(last: str | None, current: str = __version__) -> bool:
    """Is this the first start after an update (``last``: the version of the last start, "" when unknown)?"""
    return bool(last) and parse_version(last) < parse_version(current)


# ----------------------------------------------------------------------- installing
PORTABLE_MARKER = "portable.txt"  # next to the exe of the portable ZIP (added by the CI when it zips)


def build_info(exe: str | None = None) -> tuple[str, str]:
    """(edition, mode) of this build: ("cpu" | "gpu", "installed" | "portable" | "portable-zip"),
    ("dev", "dev") from source. The installer and the portable ZIP hold the same onedir build; the ZIP
    has a marker file next to the exe."""
    try:
        from . import _build_info  # written by the PyInstaller spec

        edition, mode = getattr(_build_info, "EDITION", "dev"), getattr(_build_info, "MODE", "installed")
    except ImportError:
        return "dev", "dev"
    if mode == "installed" and os.path.isfile(os.path.join(os.path.dirname(exe or sys.executable), PORTABLE_MARKER)):
        mode = "portable-zip"
    return edition, mode


def patch_name(edition: str, mode: str, current: str = __version__) -> str | None:
    """The asset of a small update from ``current`` (only the changed files: tools/manifest.py, patch.iss)."""
    ed = edition.upper()
    if mode == "installed":
        return f"CLIPassoStudio-{ed}-Patch-from-{current}.exe"
    if mode == "portable-zip":
        return f"CLIPassoStudio-{ed}-Portable-Patch-from-{current}.zip"
    return None  # (the single portable exe is always replaced as a whole)


def update_files(release: dict, edition: str, mode: str,
                 current: str = __version__) -> tuple[list[dict], dict | None]:
    """The assets to download for this edition (main file first) and the checksum file – a patch from the
    running version instead of the full files when the release has one."""
    ed = edition.upper()
    sums = next((a for a in release.get("assets", []) if a["name"] == f"SHA256SUMS-{ed}.txt"), None)
    patch = patch_name(edition, mode, current)
    patch_asset = next((a for a in release.get("assets", []) if a["name"] == patch), None) if patch else None
    if patch_asset is not None:
        return [patch_asset], sums
    if mode == "installed":
        prefix, main = f"CLIPassoStudio-{ed}-Setup", ".exe"  # + the .bin slices of the GPU setup
        assets = [a for a in release.get("assets", []) if a["name"].startswith(prefix)]
    elif mode in ("portable", "portable-zip"):
        name = f"CLIPassoStudio-{ed}-Portable" + (".exe" if mode == "portable" else ".zip")
        main = name[-4:]
        assets = [a for a in release.get("assets", []) if a["name"] == name]
    else:
        return [], None
    files = sorted(assets, key=lambda a: (not a["name"].endswith(main), a["name"]))
    return files, sums


def can_install(release: dict, edition: str | None = None, mode: str | None = None) -> bool:
    if edition is None or mode is None:
        edition, mode = build_info()
    files, sums = update_files(release, edition, mode)
    return bool(files) and sums is not None and files[0]["name"].endswith((".exe", ".zip"))


def parse_sums(text: str) -> dict[str, str]:
    """``sha256sum`` output -> {file name: sha256}."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[os.path.basename(m.group(2))] = m.group(1).lower()
    return out


def updates_dir(tag: str) -> Path:
    return paths.user_data_dir() / "updates" / re.sub(r"[^A-Za-z0-9._-]", "_", tag)


def remove_old_updates(current: str = __version__) -> int:
    """Delete the downloads of updates that are installed by now (this version or older); a newer
    one that is only partly downloaded stays. Returns the bytes freed."""
    root = paths.user_data_dir() / "updates"
    freed = 0
    if not root.is_dir():
        return 0
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            older = parse_version(d.name) <= parse_version(current)
        except ValueError:
            older = True
        if older:
            freed += folder_size(d)
            shutil.rmtree(d, ignore_errors=True)
    return freed


def download_update(release: dict, edition: str | None = None, mode: str | None = None, dest_dir=None,
                    progress=None, cancel=None) -> str:
    """Download and verify the update files of this edition; returns the file to start (setup / exe).
    Files already downloaded and verified are kept, interrupted ones continue."""
    from ..engine.model_store import _download_url, _sha256

    if edition is None or mode is None:
        edition, mode = build_info()
    files, sums = update_files(release, edition, mode)
    if not files or sums is None:
        raise UserError("update_no_files", "this release has no files for this edition")
    dest = Path(dest_dir) if dest_dir else updates_dir(release["tag"])
    dest.mkdir(parents=True, exist_ok=True)
    left = sum(f["size"] - ((dest / f["name"]).stat().st_size if (dest / f["name"]).is_file() else 0)
               for f in files)
    ensure_space(dest, max(left, 0), "update")
    sums_path = dest / sums["name"]
    _download_url(sums["url"], sums_path, None, cancel)
    expected = parse_sums(sums_path.read_text(encoding="utf-8", errors="replace"))
    total = sum(f["size"] for f in files) or 1
    done = 0
    for f in files:
        target = dest / f["name"]
        digest = expected.get(f["name"])
        if not digest:
            raise UserError("update_no_checksum", f"{f['name']} is missing in {sums['name']}", file=f["name"])
        ok_marker = target.with_name(target.name + ".ok")
        if target.is_file() and not ok_marker.is_file() and target.stat().st_size == f["size"]:
            # complete, but the check did not finish last time (app closed): check instead of loading again
            if progress:
                progress(0, 0)
            if _sha256(target) == digest:
                ok_marker.write_text(digest, encoding="utf-8")
            else:
                target.unlink()
        if not (target.is_file() and ok_marker.is_file() and target.stat().st_size == f["size"]):
            offset = target.stat().st_size if target.is_file() and target.stat().st_size < f["size"] else 0
            if offset == 0 and target.exists():
                target.unlink()
            base = done
            prog = (lambda d, t, base=base: progress(min(base + d, total), total)) if progress else None
            _download_url(f["url"], target, prog, cancel, offset=offset)
            if progress:
                progress(0, 0)  # checking
            if _sha256(target) != digest:
                target.unlink()
                raise UserError("update_checksum", f"{f['name']}: the checksum does not match – please try again",
                                file=f["name"])
            ok_marker.write_text(digest, encoding="utf-8")
        done += f["size"]
        if progress:
            progress(done, total)
    return str(dest / files[0]["name"])


APP_GUID = "{7C1E2B64-3F7A-4E56-9B8B-C1A55C0D2A11}"  # AppId of packaging/installer.iss (+ "_<EDITION>")
_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{guid}_{edition}_is1"


def _registered_scope(edition: str) -> str | None:
    """Where Inno Setup registered this edition: "all" (HKLM), "user" (HKCU) or None (unknown)."""
    if sys.platform != "win32":
        return None
    import winreg

    key = _UNINSTALL_KEY.format(guid=APP_GUID, edition=edition.upper())
    for hive, scope in ((winreg.HKEY_LOCAL_MACHINE, "all"), (winreg.HKEY_CURRENT_USER, "user")):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                winreg.CloseKey(winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view))
                return scope
            except OSError:
                continue
    return None


def _folder_writable(folder: str) -> bool:
    """Can this user create files in ``folder``? (os.access(W_OK) is always true for folders on Windows.)"""
    probe = os.path.join(folder, f".clipasso-write-test-{os.getpid()}")
    try:
        with open(probe, "w", encoding="utf-8"):
            pass
    except OSError:
        return False
    try:
        os.remove(probe)
    except OSError:
        pass
    return True


def all_users_install(app_dir: str, edition: str = "cpu") -> bool:
    """Was the app installed for all users? The installer's registration decides; without one, a
    folder that needs admin rights to write (e.g. under Program Files) means all users."""
    scope = _registered_scope(edition)
    if scope is not None:
        return scope == "all"
    return not _folder_writable(app_dir)


def install_command(path: str, mode: str, app_dir: str | None = None,
                    edition: str | None = None) -> tuple[str, list[str]]:
    """How to start the downloaded update. The installer runs silently for the same kind of
    installation as the running app (all users or the current user only)."""
    if mode == "installed":
        app_dir = app_dir or os.path.dirname(sys.executable)
        edition = edition or build_info()[0]
        scope = "/ALLUSERS" if all_users_install(app_dir, edition) else "/CURRENTUSER"
        return path, ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", scope, "/UPDATE"]
    if mode == "portable-zip":  # the new version offers to delete this one's folder
        return path, [AFTER_UPDATE_ARG, app_dir or os.path.dirname(sys.executable)]
    return path, []


def place_portable(path: str, version: str, exe: str | None = None) -> str:
    """Copy the new portable exe next to the running one (or into Downloads when that folder is
    read-only) as ``CLIPassoStudio-<edition>-Portable-<version>.exe``."""
    exe = exe or sys.executable
    stem, ext = os.path.splitext(os.path.basename(path))
    name = f"{stem}-{version.lstrip('v')}{ext}"
    for folder in (os.path.dirname(exe), str(Path.home() / "Downloads"), os.path.dirname(path)):
        try:
            os.makedirs(folder, exist_ok=True)
            target = os.path.join(folder, name)
            shutil.copyfile(path, target)
            return target
        except OSError:
            continue
    return path


# ----------------------------------------------------------------------- portable ZIP

AFTER_UPDATE_ARG = "--after-update"  # started by the previous portable version: <its folder> follows
APP_EXE = "CLIPassoStudio.exe"


REMOVED_LIST = "removed.txt"  # in a patch ZIP: the files the new version does not have any more


def _patch_root(names: list[str]) -> str | None:
    """The folder of a patch ZIP's files ("" or "<folder>/"); None for a full portable ZIP."""
    for n in names:
        if n == REMOVED_LIST:
            return ""
        if n.endswith("/" + REMOVED_LIST) and n.count("/") == 1:
            return n[: -len(REMOVED_LIST)]
    return None


def place_portable_zip(path: str, version: str, app_dir: str | None = None, progress=None) -> str:
    """Unpack the portable ZIP next to the running version's folder (or into Downloads when that place
    is read-only) as ``CLIPasso Studio <version>``; returns the new exe. A patch ZIP (only the changed files
    and ``removed.txt``) is applied to a copy of the running version."""
    import zipfile

    app_dir = os.path.abspath(app_dir or os.path.dirname(sys.executable))
    name = f"CLIPasso Studio {version.lstrip('v')}"
    errors = []
    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        patch = _patch_root([m.filename.replace("\\", "/") for m in members])
        if patch is None:
            exe = next((m.filename for m in members
                        if m.filename.replace("\\", "/").rsplit("/", 1)[-1] == APP_EXE), None)
            if exe is None:
                raise UserError("update_no_files", f"{os.path.basename(path)} holds no {APP_EXE}")
            root = exe.replace("\\", "/").rsplit("/", 1)[0] + "/" if "/" in exe.replace("\\", "/") else ""
        else:
            root = patch
        total = sum(m.file_size for m in members) or 1
        for parent in (os.path.dirname(app_dir), str(Path.home() / "Downloads")):
            target = os.path.join(parent, name)
            n = 1
            while os.path.exists(target):
                n += 1
                target = os.path.join(parent, f"{name} ({n})")
            tmp = target + ".partial"
            try:
                ensure_space(parent, total + (folder_size(app_dir) if patch is not None else 0), "update")
                shutil.rmtree(tmp, ignore_errors=True)
                if patch is not None:  # the running version, then the changed files over it
                    shutil.copytree(app_dir, tmp)
                done = 0
                for m in members:
                    rel = m.filename.replace("\\", "/")
                    if not rel.startswith(root) or (patch is not None and rel == root + REMOVED_LIST):
                        continue
                    dest = os.path.normpath(os.path.join(tmp, rel[len(root):]))
                    if not dest.startswith(os.path.normpath(tmp) + os.sep):
                        continue  # no paths out of the folder
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(m) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out, 1 << 20)
                    done += m.file_size
                    if progress:
                        progress(done, total)
                if patch is not None:
                    for rel in zf.read(root + REMOVED_LIST).decode("utf-8", "replace").splitlines():
                        dest = os.path.normpath(os.path.join(tmp, rel.strip()))
                        if rel.strip() and dest.startswith(os.path.normpath(tmp) + os.sep) and os.path.isfile(dest):
                            os.remove(dest)
                os.replace(tmp, target)
                return os.path.join(target, APP_EXE)
            except UserError:
                raise
            except OSError as exc:
                errors.append(f"{parent}: {exc}")
                shutil.rmtree(tmp, ignore_errors=True)
    raise UserError("update_unpack", "could not unpack the update: " + "; ".join(errors), details="; ".join(errors))


def is_old_portable_folder(folder: str, current_exe: str | None = None) -> bool:
    """Is ``folder`` the folder of an earlier portable ZIP version (safe to delete)? It must hold the app's
    exe, its ``_internal`` folder and the portable marker, and must not be the running version."""
    if not folder or not os.path.isdir(folder):
        return False
    here = os.path.normcase(os.path.abspath(os.path.dirname(current_exe or sys.executable)))
    if os.path.normcase(os.path.abspath(folder)) == here:
        return False
    return all(os.path.exists(os.path.join(folder, n)) for n in (APP_EXE, "_internal", PORTABLE_MARKER))


def remove_folder(folder: str, attempts: int = 20, wait: float = 0.5) -> bool:
    """Delete an old version's folder; its exe may still be closing, so a few tries."""
    import time

    for _ in range(attempts):
        shutil.rmtree(folder, ignore_errors=True)
        if not os.path.exists(folder):
            return True
        time.sleep(wait)
    return False
