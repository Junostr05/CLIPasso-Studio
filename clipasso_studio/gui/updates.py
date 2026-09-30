"""Update notice: is a newer CLIPasso Studio release available on GitHub?

Only asks the GitHub API for the latest release (no data is sent, nothing is installed); pre-releases
are ignored. Offline or on any error the check simply finds nothing.
"""

from __future__ import annotations

import json
import re
import urllib.request

from .. import __version__

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
    return {"tag": data["tag_name"], "url": data.get("html_url") or RELEASES_PAGE, "name": data.get("name") or ""}


def check(progress=None, url: str = RELEASES_API, current: str = __version__) -> str:
    """For ``run_in_thread``: the newer release as JSON, or "" (up to date, offline, error)."""
    try:
        release = latest_release(url)
    except Exception:
        return ""
    if release and is_newer(release["tag"], current):
        return json.dumps(release)
    return ""
