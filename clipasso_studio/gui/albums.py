"""Albums: named groups of results in the gallery. A result knows its albums (``"albums"`` in its ``meta.json``, so
they move with it and survive a backup); the app settings keep the order of the albums and the empty ones."""

from __future__ import annotations

from ..engine import jobs
from .app_settings import app_settings

SETTING = "albums"
MAX_NAME = 60


def clean(name: str) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME]


def of(summary: dict) -> list[str]:
    """The albums of a job summary (its ``meta.json`` merged into it)."""
    albums = summary.get("albums") or []
    return [str(a) for a in albums] if isinstance(albums, list) else []


def names(summaries: list[dict] = ()) -> list[str]:
    """All albums: the ones the app knows in their order, then those only found in the results."""
    stored = [clean(a) for a in app_settings().get(SETTING) or [] if clean(a)]
    seen = {a.lower() for a in stored}
    extra = sorted({a for s in summaries for a in of(s) if a.lower() not in seen}, key=str.lower)
    return stored + extra


def _store(albums: list[str]) -> None:
    out, seen = [], set()
    for a in albums:
        a = clean(a)
        if a and a.lower() not in seen:
            out.append(a)
            seen.add(a.lower())
    app_settings().set(SETTING, out)


def create(name: str) -> str:
    """A new (empty) album; returns its name ("" when the name is empty)."""
    name = clean(name)
    if name:
        _store(list(app_settings().get(SETTING) or []) + [name])
    return name


def _set(job_dir: str, albums: list[str]) -> list[str]:
    meta = jobs.write_meta(job_dir, albums=albums or None)
    return list(meta.get("albums") or [])


def add(job_dirs: list[str], name: str) -> int:
    """Put results into an album (created when new); returns how many were added."""
    name = create(name) if clean(name) else ""
    if not name:
        return 0
    added = 0
    for d in job_dirs:
        current = list(jobs.read_meta(d).get("albums") or [])
        if name not in current:
            _set(d, current + [name])
            added += 1
    return added


def remove(job_dirs: list[str], name: str) -> int:
    removed = 0
    for d in job_dirs:
        current = list(jobs.read_meta(d).get("albums") or [])
        if name in current:
            _set(d, [a for a in current if a != name])
            removed += 1
    return removed


def rename(job_dirs: list[str], old: str, new: str) -> str:
    """Rename an album in the settings and in every result (``job_dirs``: all results); returns the new name."""
    new = clean(new)
    if not new or new == old:
        return old
    for d in job_dirs:
        current = list(jobs.read_meta(d).get("albums") or [])
        if old in current:
            _set(d, list(dict.fromkeys(new if a == old else a for a in current)))
    _store([new if a == old else a for a in app_settings().get(SETTING) or []] +
           ([] if old in (app_settings().get(SETTING) or []) else [new]))
    return new


def delete(job_dirs: list[str], name: str) -> None:
    """Remove an album – the results stay in the gallery."""
    remove(job_dirs, name)
    _store([a for a in app_settings().get(SETTING) or [] if a != name])
