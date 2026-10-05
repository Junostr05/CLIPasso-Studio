"""Backup & move: everything of the app in one ``.clipbackup`` file (a ZIP) – the settings, the queue with its
input pictures, the gallery (every job folder with its sketches, albums, names and notes) and, if wanted, the
downloaded models – and putting it back on this or another computer.

On restoring, the folders of this computer stay (output folder, model folder, window, graphics card add-on); paths
in the queue are moved to them, jobs that are already there are skipped (the same folder name), as are models
with the same size. The jobs find their files again by themselves (``jobs.rebase``)."""

from __future__ import annotations

import json
import os
import time
import zipfile
from pathlib import Path

from .. import APP_NAME, __version__, fileops, paths
from .app_settings import app_settings
from .storage import relocated, result_entries

EXTENSION = ".clipbackup"
FORMAT = 1
MANIFEST = "manifest.json"
SETTINGS = "settings.json"
GALLERY = "gallery/"
QUEUE_INPUTS = "queue_inputs/"
MODELS = "models/"
PARTS = ("settings", "queue", "gallery", "models")
# settings of this computer: never taken over from a backup
LOCAL_KEYS = {"output_dir", "models_dir", "geometry", "gpu_runtime", "gpu_runtime_dismissed", "settings_version",
              "last_version", "skipped_version", "queue", "ui_scale", "watch_folder", "watch_export_dir", "export_dir",
              "batch_export_dir"}
SECRET_KEYS = {"telegram_token", "telegram_chat", "telegram_bot", "remote_token"}  # never in a backup file
STORED = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".pt", ".pth", ".safetensors", ".bin", ".onnx", ".zip",
          ".heic", ".avif"}  # already compressed: stored as they are (faster)


class BackupError(Exception):
    pass


def _files(folder: str) -> list[tuple[str, str]]:
    """(path, path relative to ``folder`` with "/") of every file below it."""
    out = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            p = os.path.join(root, name)
            out.append((p, os.path.relpath(p, folder).replace(os.sep, "/")))
    return sorted(out, key=lambda x: x[1])


def _inside(path: str, folder: str) -> bool:
    p, f = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return p.startswith(f.rstrip("\\/") + os.sep)


def _queue_targets() -> list[str]:
    return [str(item.get("target") or "") for item in app_settings().get("queue") or [] if isinstance(item, dict)]


def sizes(include_models: bool = False) -> dict:
    """What a backup would hold: bytes per part and the number of jobs."""
    out_dir = app_settings().get("output_dir") or ""
    entries = result_entries(out_dir) if out_dir else []
    gallery = sum(fileops.folder_size(os.path.join(out_dir, n)) for n in entries)
    queue = sum(os.path.getsize(t) for t in _queue_targets() if t and os.path.isfile(t))
    models = fileops.folder_size(paths.downloaded_models_dir()) if include_models else 0
    return {"settings": paths.app_settings_file().stat().st_size if paths.app_settings_file().is_file() else 0,
            "queue": queue, "gallery": gallery, "models": models,
            "jobs": sum(1 for n in entries if not n.startswith("_"))}


def models_size() -> int:
    return fileops.folder_size(paths.downloaded_models_dir())


def create(dest: str, include_models: bool = False, progress=None, cancel=None) -> dict:
    """Write a backup to ``dest``; returns its manifest. ``progress(done_bytes, all_bytes)``; ``cancel()`` → True
    stops (InterruptedError) and removes the unfinished file."""
    st = app_settings()
    st.save()
    out_dir = st.get("output_dir") or ""
    models_dir = str(paths.downloaded_models_dir())
    todo: list[tuple[str, str]] = []  # (file, name in the ZIP)
    entries = result_entries(out_dir) if out_dir and os.path.isdir(out_dir) else []
    for name in entries:
        todo += [(p, f"{GALLERY}{name}/{rel}") for p, rel in _files(os.path.join(out_dir, name))]
    queue = []
    for i, item in enumerate(st.get("queue") or []):
        if not isinstance(item, dict):
            continue
        item = dict(item)
        target = str(item.get("target") or "")
        if target and os.path.isfile(target):
            if not (out_dir and _inside(target, out_dir)):  # a picture from elsewhere: it travels with the backup
                arc = f"{QUEUE_INPUTS}{i:03d}_{os.path.basename(target)}"
                todo.append((target, arc))
                item["backup_target"] = arc
        queue.append(item)
    if include_models and os.path.isdir(models_dir):
        todo += [(p, f"{MODELS}{rel}") for p, rel in _files(models_dir) if not rel.startswith(".partial")]
    total = sum(os.path.getsize(p) for p, _ in todo)
    fileops.ensure_space(os.path.dirname(os.path.abspath(dest)) or ".", total, "backup")
    settings = {k: v for k, v in st.data.items() if k not in SECRET_KEYS}
    settings["queue"] = queue
    manifest = {"format": FORMAT, "app": APP_NAME, "version": __version__,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"), "output_dir": out_dir, "models_dir": models_dir,
                "jobs": sum(1 for n in entries if not n.startswith("_")), "queue": len(queue),
                "models": bool(include_models), "bytes": total}
    done = 0
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))
            z.writestr(SETTINGS, json.dumps(settings, indent=2, ensure_ascii=False))
            for path, arc in todo:
                if cancel and cancel():
                    raise InterruptedError("backup cancelled")
                kind = zipfile.ZIP_STORED if os.path.splitext(path)[1].lower() in STORED else zipfile.ZIP_DEFLATED
                try:
                    z.write(path, arc, compress_type=kind)
                except FileNotFoundError:  # (removed meanwhile)
                    continue
                done += os.path.getsize(path) if os.path.exists(path) else 0
                if progress:
                    progress(done, total)
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise
    return manifest


def read_manifest(path: str) -> dict:
    """The manifest of a backup file (BackupError when it is not one)."""
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read(MANIFEST).decode("utf-8"))
            names = z.namelist()
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise BackupError(f"not a {APP_NAME} backup: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format", 0) > FORMAT:
        raise BackupError("this backup was made by a newer version of the app")
    manifest["gallery_names"] = sorted({n[len(GALLERY):].split("/")[0] for n in names if n.startswith(GALLERY)})
    manifest["has_models"] = any(n.startswith(MODELS) for n in names)
    return manifest


def _safe_target(root: str, rel: str) -> str | None:
    """``root/rel`` – None when ``rel`` would leave ``root`` (a damaged or crafted file)."""
    dest = os.path.normpath(os.path.join(root, rel))
    root = os.path.normpath(root)
    return dest if dest == root or dest.startswith(root + os.sep) else None


def rewrite_paths(folder: str, old: str, new: str) -> int:
    """The absolute paths a job saved (job.json, its state, config.json of the runs) moved from below ``old`` to
    below ``new`` – also where the old folder still exists (a copy must not point to the originals). Returns the
    number of files changed."""
    if not old or os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(new)):
        return 0

    def fix(v):
        if isinstance(v, str):
            return relocated(v, old, new) if os.path.isabs(v) else v
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        return v

    changed = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if not name.endswith(".json"):
                continue
            p = os.path.join(root, name)
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            moved = fix(data)
            if moved != data:
                with open(p + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(moved, f, indent=2, ensure_ascii=False)
                os.replace(p + ".tmp", p)
                changed += 1
    return changed


def restore(path: str, parts=PARTS, progress=None, cancel=None) -> dict:
    """Put a backup back (the ``parts`` of PARTS). Returns what was done: {"settings": bool, "queue": [new entries],
    "jobs": n, "skipped_jobs": n, "models": n files}. The queue entries are only returned – the caller adds them to
    the running queue (they are not written to the settings here)."""
    manifest = read_manifest(path)
    st = app_settings()
    out_dir = st.get("output_dir") or str(paths.default_output_dir())
    old_out = manifest.get("output_dir") or ""
    report = {"settings": False, "queue": [], "jobs": 0, "skipped_jobs": 0, "models": 0}
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        total = sum(i.file_size for i in infos)
        done = 0

        def tick(info):
            nonlocal done
            done += info.file_size
            if progress:
                progress(done, total)
            if cancel and cancel():
                raise InterruptedError("restore cancelled")

        saved = json.loads(z.read(SETTINGS).decode("utf-8"))
        if "settings" in parts:
            for key, value in saved.items():
                if key not in LOCAL_KEYS and key not in SECRET_KEYS:
                    st.data[key] = value
            st.data["recent_images"] = [relocated(p, old_out, out_dir) for p in saved.get("recent_images") or []]
            st.data["last_image"] = relocated(saved.get("last_image") or "", old_out, out_dir)
            st.save()
            report["settings"] = True
        existing = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()
        if "gallery" in parts:
            os.makedirs(out_dir, exist_ok=True)
            skipped = set()
            for info in infos:
                if not info.filename.startswith(GALLERY) or info.is_dir():
                    continue
                rel = info.filename[len(GALLERY):]
                job = rel.split("/")[0]
                if job in existing and not job.startswith("_"):
                    skipped.add(job)  # the same job is here already
                    continue
                dest = _safe_target(out_dir, rel)
                if dest is None or (job.startswith("_") and os.path.exists(dest)):
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as f:
                    while chunk := src.read(1 << 20):
                        f.write(chunk)
                tick(info)
            restored = {n for n in manifest["gallery_names"] if not n.startswith("_")} - skipped
            for name in restored:
                rewrite_paths(os.path.join(out_dir, name), old_out, out_dir)
            report["jobs"], report["skipped_jobs"] = len(restored), len(skipped)
        if "queue" in parts:
            inputs = paths.user_data_dir() / "restored_inputs"
            known = {(str(i.get("target")), json.dumps(i.get("settings"), sort_keys=True))
                     for i in st.get("queue") or [] if isinstance(i, dict)}
            for item in saved.get("queue") or []:
                if not isinstance(item, dict) or not item.get("target"):
                    continue
                item = dict(item)
                arc = item.pop("backup_target", "")
                if arc:
                    inputs.mkdir(parents=True, exist_ok=True)
                    dest = inputs / os.path.basename(arc)
                    if not dest.exists():
                        with z.open(arc) as src, open(dest, "wb") as f:
                            f.write(src.read())
                    item["target"] = str(dest)
                else:
                    item["target"] = relocated(item["target"], old_out, out_dir)
                for key in ("job_dir", "resume_dir"):
                    if item.get(key):
                        item[key] = relocated(item[key], old_out, out_dir)
                settings = item.get("settings") or {}
                if isinstance(settings, dict) and settings.get("path_svg"):
                    item["settings"] = {**settings, "path_svg": relocated(settings["path_svg"], old_out, out_dir)}
                key = (str(item["target"]), json.dumps(item.get("settings"), sort_keys=True))
                if key not in known:
                    known.add(key)
                    report["queue"].append(item)
        if "models" in parts and manifest.get("has_models"):
            models_dir = str(paths.downloaded_models_dir())
            for info in infos:
                if not info.filename.startswith(MODELS) or info.is_dir():
                    continue
                dest = _safe_target(models_dir, info.filename[len(MODELS):])
                if dest is None or (os.path.isfile(dest) and os.path.getsize(dest) == info.file_size):
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(info) as src, open(dest + ".part", "wb") as f:
                    while chunk := src.read(1 << 20):
                        f.write(chunk)
                os.replace(dest + ".part", dest)
                report["models"] += 1
                tick(info)
    return report


def default_name() -> str:
    return f"CLIPassoStudio-{time.strftime('%Y-%m-%d')}{EXTENSION}"


def is_backup(path: str) -> bool:
    return Path(path).suffix.lower() == EXTENSION
