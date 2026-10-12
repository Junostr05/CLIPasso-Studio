"""Small updates: the file list of a build (path -> SHA-256 and size), the difference to the previous release
and the folder of a patch with only the changed files.

    python tools/manifest.py build DIST_DIR --edition CPU --version 3.2.0 --out manifest.json
    python tools/manifest.py previous --edition CPU --tag v3.2.0 --repo OWNER/REPO --out prev.json
    python tools/manifest.py patch PREV.json NEW.json DIST_DIR PATCH_DIR [--max-share 0.4]
    python tools/manifest.py fake-previous NEW.json --version 3.2.0 --out prev.json   (CI test of a patch)

``patch`` copies the changed and new files into ``PATCH_DIR`` (same layout), writes ``removed.txt`` (one
relative path per line) and ``removed.iss`` (``[InstallDelete]`` lines for packaging/patch.iss) and prints a
JSON line: {"ok": …, "from": version, "changed": n, "removed": n, "bytes": …, "total": …}. "ok" is false when
the patch would not be small (more than ``max_share`` of the build changed, e.g. a new PyTorch).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXCLUDE = {"portable.txt"}  # (the portable ZIP's marker: an installed app must never get it)
MAX_SHARE = 0.4


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(folder: str | Path, edition: str, version: str) -> dict:
    folder = Path(folder)
    files = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        if rel in EXCLUDE:
            continue
        files[rel] = {"sha256": sha256(path), "size": path.stat().st_size}
    return {"edition": edition.upper(), "version": version.lstrip("v"), "files": files}


def diff(old: dict, new: dict) -> tuple[list[str], list[str]]:
    """(changed or new paths, removed paths) from ``old`` to ``new``."""
    a, b = old.get("files", {}), new.get("files", {})
    changed = sorted(p for p, f in b.items() if a.get(p, {}).get("sha256") != f["sha256"])
    removed = sorted(p for p in a if p not in b)
    return changed, removed


def make_patch(old: dict, new: dict, dist: str | Path, out: str | Path, max_share: float = MAX_SHARE) -> dict:
    dist, out = Path(dist), Path(out)
    changed, removed = diff(old, new)
    size = sum(new["files"][p]["size"] for p in changed)
    total = sum(f["size"] for f in new["files"].values()) or 1
    info = {"ok": size <= max_share * total, "from": old.get("version", ""), "changed": len(changed),
            "removed": len(removed), "bytes": size, "total": total}
    if not info["ok"]:
        return info
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for rel in changed:
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dist / rel, target)
    (out / "removed.txt").write_text("".join(f"{p}\n" for p in removed), encoding="utf-8")
    iss = "".join(f'Type: files; Name: "{{app}}\\{p.replace("/", chr(92))}"\n' for p in removed)
    (out.parent / f"{out.name}-removed.iss").write_text(iss or "; nothing removed\n", encoding="utf-8")
    return info


def fake_previous(new: dict, version: str, extra: str = "_internal/left_from_the_previous_version.txt") -> dict:
    """A stand-in "previous release" for testing a patch in the CI: this build's manifest with three files
    changed (the exe among them) and one file more (the patch must delete it)."""
    files = {k: dict(v) for k, v in new["files"].items()}
    smallest = sorted((k for k in files if k != "CLIPassoStudio.exe"), key=lambda k: files[k]["size"])[:2]
    for k in ["CLIPassoStudio.exe", *smallest]:
        if k in files:
            files[k]["sha256"] = "0" * 64
    files[extra] = {"sha256": "1" * 64, "size": 1}
    return {**new, "version": version.lstrip("v"), "files": files}


def parse_version(text: str) -> tuple:
    from clipasso_studio.gui.updates import parse_version as pv

    return pv(text)


def is_beta(tag: str) -> bool:
    """A pre-release tag (v4.0.0b1, v2.1.0-beta.1, …): its version ranks below the final one."""
    return len(parse_version(tag)) > 3 and parse_version(tag)[3] < 3


def _releases(repo: str, token: str = "") -> list[dict]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "CLIPassoStudio-CI"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=30", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def previous_manifest(repo: str, edition: str, tag: str, token: str = "", beta: bool = False) -> dict | None:
    """The manifest of the newest final release before ``tag`` – for a beta the newest release of any kind
    (who installs betas updates from the beta before) – None: there is none or it has no manifest.

    ``beta``: for a final release, the newest beta before it instead – when it is newer than that final release
    (who tried the betas gets a small update to the final one, too); None otherwise."""
    releases = _releases(repo, token)
    current = parse_version(tag)
    earlier = [r for r in releases if not r.get("draft") and r.get("tag_name") != tag
               and parse_version(r.get("tag_name", "")) < current]
    finals = [r for r in earlier if not r.get("prerelease")]
    if beta:
        if is_beta(tag):
            return None
        newest_final = max((parse_version(r["tag_name"]) for r in finals), default=None)
        earlier = [r for r in earlier if r.get("prerelease")
                   and (newest_final is None or parse_version(r["tag_name"]) > newest_final)]
    elif not is_beta(tag):
        earlier = finals
    if not earlier:
        return None
    prev = max(earlier, key=lambda r: parse_version(r["tag_name"]))
    name = f"CLIPassoStudio-{edition.upper()}-manifest.json"
    asset = next((a for a in prev.get("assets", []) if a["name"] == name), None)
    if asset is None:
        return None
    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "CLIPassoStudio-CI"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def release_manifest(repo: str, edition: str, tag: str, token: str = "") -> dict | None:
    """The manifest of the release ``tag`` (None: no such release, or it has no manifest) – for a small update from
    a version further back, e.g. the one many still have (4.2.2: from 3.8.1)."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "CLIPassoStudio-CI"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            release = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    name = f"CLIPassoStudio-{edition.upper()}-manifest.json"
    asset = next((a for a in release.get("assets", []) if a["name"] == name), None)
    if asset is None:
        return None
    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "CLIPassoStudio-CI"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("dist")
    b.add_argument("--edition", required=True)
    b.add_argument("--version", required=True)
    b.add_argument("--out", required=True)
    p = sub.add_parser("previous")
    p.add_argument("--edition", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--beta-out", default="", help="also the newest beta before a final release (its own patch)")
    r = sub.add_parser("release")
    r.add_argument("--edition", required=True)
    r.add_argument("--tag", required=True)
    r.add_argument("--repo", required=True)
    r.add_argument("--out", required=True)
    m = sub.add_parser("patch")
    m.add_argument("old")
    m.add_argument("new")
    m.add_argument("dist")
    m.add_argument("out")
    m.add_argument("--max-share", type=float, default=MAX_SHARE)
    f = sub.add_parser("fake-previous")
    f.add_argument("new")
    f.add_argument("--version", required=True)
    f.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "fake-previous":
        new = json.loads(Path(args.new).read_text(encoding="utf-8"))
        Path(args.out).write_text(json.dumps(fake_previous(new, args.version)), encoding="utf-8")
        return 0

    if args.cmd == "build":
        data = build(args.dist, args.edition, args.version)
        Path(args.out).write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"manifest: {len(data['files'])} files")
        return 0
    if args.cmd == "previous":
        token = os.environ.get("GITHUB_TOKEN", "")
        data = previous_manifest(args.repo, args.edition, args.tag, token)
        if data is None:
            print("manifest: no earlier release with a manifest – no patch")
        else:
            Path(args.out).write_text(json.dumps(data), encoding="utf-8")
            print(f"manifest: previous release {data.get('version')}")
        if args.beta_out:
            beta = previous_manifest(args.repo, args.edition, args.tag, token, beta=True)
            if beta is not None:
                Path(args.beta_out).write_text(json.dumps(beta), encoding="utf-8")
                print(f"manifest: and the beta before it {beta.get('version')}")
        return 0
    if args.cmd == "release":
        data = release_manifest(args.repo, args.edition, args.tag, os.environ.get("GITHUB_TOKEN", ""))
        if data is None:
            print(f"manifest: {args.tag} has none – no patch from it")
        else:
            Path(args.out).write_text(json.dumps(data), encoding="utf-8")
            print(f"manifest: release {data.get('version')}")
        return 0
    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    print(json.dumps(make_patch(old, new, args.dist, args.out, args.max_share)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
