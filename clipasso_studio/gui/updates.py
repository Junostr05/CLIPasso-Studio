"""Updates: is a newer CLIPasso Studio release available on GitHub – and installing it.

The check only asks the GitHub API for the latest release (no data is sent); pre-releases are
ignored, and offline or on any error it simply finds nothing. *Install* downloads the files of this
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

RELEASES_API = "https://api.github.com/repos/Junostr05/CLIPasso-Studio/releases/latest"
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


def latest_release(url: str = RELEASES_API, timeout: float = 5.0) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": "CLIPassoStudio",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease") or not data.get("tag_name"):
        return None
    assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""), "size": int(a.get("size") or 0)}
              for a in data.get("assets") or [] if isinstance(a, dict)]
    return {"tag": data["tag_name"], "url": data.get("html_url") or RELEASES_PAGE, "name": data.get("name") or "",
            "assets": assets}


def check(progress=None, url: str = RELEASES_API, current: str = __version__) -> str:
    """For ``run_in_thread``: the newer release as JSON, or "" (up to date, offline, error)."""
    try:
        release = latest_release(url)
    except Exception:
        return ""
    if release and is_newer(release["tag"], current):
        return json.dumps(release)
    return ""


# ----------------------------------------------------------------------- installing
def build_info() -> tuple[str, str]:
    """(edition, mode) of this build: ("cpu" | "gpu", "installed" | "portable"), ("dev", "dev") from source."""
    try:
        from . import _build_info  # written by the PyInstaller spec

        return getattr(_build_info, "EDITION", "dev"), getattr(_build_info, "MODE", "installed")
    except ImportError:
        return "dev", "dev"


def update_files(release: dict, edition: str, mode: str) -> tuple[list[dict], dict | None]:
    """The assets to download for this edition (main file first) and the checksum file."""
    ed = edition.upper()
    if mode == "installed":
        prefix = f"CLIPassoStudio-{ed}-Setup"
    elif mode == "portable":
        prefix = f"CLIPassoStudio-{ed}-Portable"
    else:
        return [], None
    files = sorted((a for a in release.get("assets", []) if a["name"].startswith(prefix)),
                   key=lambda a: (not a["name"].endswith(".exe"), a["name"]))
    sums = next((a for a in release.get("assets", []) if a["name"] == f"SHA256SUMS-{ed}.txt"), None)
    return files, sums


def can_install(release: dict, edition: str | None = None, mode: str | None = None) -> bool:
    if edition is None or mode is None:
        edition, mode = build_info()
    files, sums = update_files(release, edition, mode)
    return bool(files) and sums is not None and files[0]["name"].endswith(".exe")


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


def download_update(release: dict, edition: str | None = None, mode: str | None = None, dest_dir=None,
                    progress=None, cancel=None) -> str:
    """Download and verify the update files of this edition; returns the file to start (setup / exe).
    Files already downloaded and verified are kept, interrupted ones continue."""
    from ..engine.model_store import _download_url, _sha256

    if edition is None or mode is None:
        edition, mode = build_info()
    files, sums = update_files(release, edition, mode)
    if not files or sums is None:
        raise RuntimeError("this release has no files for this edition")
    dest = Path(dest_dir) if dest_dir else updates_dir(release["tag"])
    dest.mkdir(parents=True, exist_ok=True)
    sums_path = dest / sums["name"]
    _download_url(sums["url"], sums_path, None, cancel)
    expected = parse_sums(sums_path.read_text(encoding="utf-8", errors="replace"))
    total = sum(f["size"] for f in files) or 1
    done = 0
    for f in files:
        target = dest / f["name"]
        digest = expected.get(f["name"])
        if not digest:
            raise RuntimeError(f"{f['name']} is missing in {sums['name']}")
        ok_marker = target.with_name(target.name + ".ok")
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
                raise RuntimeError(f"{f['name']}: the checksum does not match – please try again")
            ok_marker.write_text(digest, encoding="utf-8")
        done += f["size"]
        if progress:
            progress(done, total)
    return str(dest / files[0]["name"])


def install_command(path: str, mode: str, app_dir: str | None = None) -> tuple[str, list[str]]:
    """How to start the downloaded update. The installer runs silently for the same kind of
    installation (all users when the app folder is not writable, e.g. under Program Files)."""
    if mode == "installed":
        app_dir = app_dir or os.path.dirname(sys.executable)
        scope = "/CURRENTUSER" if os.access(app_dir, os.W_OK) else "/ALLUSERS"
        return path, ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", scope, "/UPDATE"]
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
