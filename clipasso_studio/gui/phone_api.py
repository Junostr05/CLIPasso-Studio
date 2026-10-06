"""What the phone page can do in the studio – almost everything the studio itself offers: the picture (photo, file,
recent pictures, samples), the method, presets, every parameter, the time budget, the detail brush and portrait
mode, start / queue / pause / cancel, the sketches of the shown job with their numbers, thumbs, brush style and
paper, downloads, the recent results and the queue.

``PhoneApi.handle(action, data)`` runs in the GUI thread (the server threads ask through ``RemoteBridge.call``) and
never opens a dialog on the computer: questions (memory short, models missing) go back to the phone as answers."""

from __future__ import annotations

import io
import os

import numpy as np

from .. import paths
from .. import settings_schema as schema
from ..engine import details, jobs, model_store
from . import export_jobs, methods_ui, user_presets
from .app_settings import app_settings
from .i18n import i18n, tr

RESULTS_MAX = 40
INPUT_SIDE = 900  # the picture as the phone sees it (and paints the detail map on)


class PhoneError(Exception):
    """An answer for the phone (shown there), not a fault."""


def _jpeg(path: str, side: int) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice

    from .image_io import read_image

    img = read_image(path, side)
    if img.isNull():
        raise PhoneError(tr("ui.phone.page.no_picture"))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPEG", 85)
    return bytes(buf.data())


def imaging_eta(seconds) -> str:
    from ..engine.imaging import eta_string

    return eta_string(seconds) if seconds else ""


def _file(data: bytes, ctype: str, name: str = "") -> dict:
    return {"_bytes": data, "_type": ctype, "_name": name}


def _choice_label(method: str, param: schema.Param, value) -> str:
    from .widgets.param_panel import param_text_key

    key = param_text_key(method, param.key, f"choice.{value}")
    return tr(key) if i18n.has(key) else str(value)


class PhoneApi:
    def __init__(self, controller, studio=None, link=None):
        self.controller = controller
        self.studio = studio
        self.link = link
        self.note = ""  # a message for the phone (e.g. the result of "find face"), shown once
        self._note_id = 0
        self._details_rev = 0
        self._cache = None
        self._exports: dict[str, dict] = {}  # the phone's exports (id -> state), files in export_root()
        self.gallery = None  # the gallery page (deleting goes its way), set by the main window
        self.compare = None  # the compare page (its jobs and results), set by the main window
        self.models_page = None  # refreshed when the phone had models downloaded
        self._download: dict | None = None  # models downloaded on the phone's request
        self._detail_key, self._detail_at = None, None
        self._taste_key, self._taste_value = None, None

    # ------------------------------------------------------------------ dispatch
    def handle(self, action: str, data: dict):
        if action == "set_image":
            fn = lambda d: self.set_image(str(d.get("path", "")))  # noqa: E731
        elif action == "set_details":
            fn = lambda d: self.set_details(d.get("png") or b"")  # noqa: E731
        else:
            fn = getattr(self, action, None) if action.split("_")[0] in ("get", "file", "do") else None
        if fn is None:
            return {"ok": False, "error": "unknown action"}
        if self.studio is None and action not in ("get_queue", "do_remove", "do_clear_queue"):
            return {"ok": False, "error": tr("ui.phone.page.no_studio")}
        try:
            return fn(data or {})
        except PhoneError as exc:
            return {"ok": False, "error": str(exc)}

    def _say(self, text: str):
        self.note = text
        self._note_id += 1

    # ------------------------------------------------------------------ state
    def signature(self) -> tuple:
        """A cheap fingerprint of what the page shows – when it changes, the open pages are told (live updates)."""
        c, s = self.controller, self.studio
        queue = tuple((id(j), j.status, round(float(j.progress or 0), 3)) for j in c.jobs)
        if s is None:
            return (queue,)
        st = app_settings()
        return (queue, s.params.method(), tuple(sorted(s.params.settings().items())), s.params.user_preset(),
                s.image_path, s.view_dir, s.selected_seed, s.best_seed,
                tuple((seed, hash(svg)) for seed, svg in s.seed_svgs.items()), s.status.text(),
                s.progress.value(), s.estimate.text(), self._note_id, self._details_rev,
                st.get("canvas_style"), st.get("canvas_paper"), repr(st.get("user_presets")),
                repr(self._download_state()), s.mask_status.text())

    def get_studio(self, data: dict) -> dict:
        s = self.studio
        c = self.controller
        method = s.params.method()
        settings = s.params.settings()
        params = [p for p in schema.params_for(method) if p.kind != "path" and not p.hidden]
        image = None
        if s.image_path and os.path.isfile(s.image_path):
            from .image_io import image_size

            size = image_size(s.image_path)
            image = {"name": os.path.basename(s.image_path), "size": f"{size.width()}×{size.height()}",
                     "rev": f"{os.path.getmtime(s.image_path):.0f}-{abs(hash(s.image_path)) % 10 ** 8}"}
        has_details = False
        if image:
            path = self._detail_file(s.image_path)
            has_details = bool(path and path.is_file())
        job = c.current if c.is_busy() else None
        seeds = []
        for seed in sorted(s.seed_svgs):
            thumb = s.thumbs.get(seed)
            seeds.append({"seed": seed, "caption": thumb.caption.text() if thumb else "",
                          "best": seed == s.best_seed, "rev": abs(hash(s.seed_svgs[seed])) % 10 ** 10})
        shown = s.selected_seed if s.selected_seed is not None else s.best_seed
        rating, can_rate = None, s._editable_seed() is not None
        if can_rate:
            rating = s._rating_of(s._editable_seed())[2]
        from ..engine.aesthetic import MIN_RATINGS
        from . import dialogs

        up, down = self._taste_counts()
        missing = methods_ui.missing_models(settings)
        st = app_settings()
        return {
            "method": method,
            "methods": [{"key": m, "name": methods_ui.name(m),
                         "missing": bool(methods_ui.missing_models(s.params.settings_for(m)))} for m in schema.METHODS],
            "missing": [dialogs.model_display_name(k) for k in missing],
            "missing_mb": round(methods_ui.download_mb(missing)) if missing else 0,
            "preset": getattr(s.params, "_preset", ""),
            "user_preset": s.params.user_preset(),
            "user_presets": [{"name": p["name"], "method": p["method"], "method_name": methods_ui.name(p["method"])}
                             for p in user_presets.all_presets()],
            "settings": {p.key: settings.get(p.key) for p in params},
            "enabled": {p.key: schema.is_enabled(p, settings) for p in params},
            "estimate": s.estimate.text(),
            "image": image,
            "details": {"has": has_details, "used": method in ("clipasso", "controlsketch"), "rev": self._details_rev},
            "busy": job is not None,
            "paused": bool(job and job.status == "paused"),
            "running_here": bool(job and job is s.view_job),
            "running": {"name": job.name, "progress": round(job.progress, 4),
                        "method": methods_ui.name(job.settings.get("method", "clipasso"))} if job else None,
            "queue": sum(1 for j in c.jobs if j.status == "queued"),
            "status": s.status.text(),
            "progress": round(s.progress.value() / max(s.progress.maximum(), 1), 4),
            "stats": [{"label": w.caption.text(), "value": w.value.text()}
                      for w in (s.stat_iter, s.stat_loss, s.stat_best, s.stat_time, s.stat_eta)],
            "view": os.path.basename(os.path.normpath(s.view_dir)) if s.view_dir else "",
            "seeds": seeds,
            "shown": shown,
            "live_rev": abs(hash(s.seed_svgs.get(shown, ""))) % 10 ** 10 if shown is not None else 0,
            "can_continue": self._can_continue(job),
            "rating": rating,
            "can_rate": can_rate,
            "taste": {"up": up, "down": down, "need": MIN_RATINGS},
            "style": st.get("canvas_style", "plain"),
            "paper": st.get("canvas_paper", "none"),
            "note": {"id": self._note_id, "text": self.note} if self.note else None,
            "scene": self._scene(shown),
            "download": self._download_state(),
            "mask": self._mask_state(),
        }

    def _scene(self, shown) -> dict | None:
        """SceneSketch: the matrix (layers × levels, which cells are there), the part being drawn, the background
        photo and whether the shown cell has its layers."""
        s = self.studio
        if s.view_method != "scenesketch" or not s.scene_layout:
            return None
        layers, levels = s.scene_layout
        cells = [{"seed": schema.scene_cell_id(layer, level), "layer": layer, "level": level,
                  "has": schema.scene_cell_id(layer, level) in s.seed_svgs,
                  "best": schema.scene_cell_id(layer, level) == s.best_seed,
                  "rev": abs(hash(s.seed_svgs.get(schema.scene_cell_id(layer, level), ""))) % 10 ** 10}
                 for layer in layers for level in levels]
        bg = self._background_file()
        return {"layers": layers, "levels": levels, "cells": cells,
                "part": s.scene_part if s.controller.is_busy() and s.view_job is s.controller.current else "",
                "background": bool(bg), "background_rev": f"{os.path.getmtime(bg):.0f}" if bg else "",
                "layered": s.layers_available(shown)}

    def _background_file(self) -> str:
        """The background behind the object as LaMa filled it in (``background.png`` of the shown job)."""
        path = os.path.join(self.studio.view_dir or "", "background.png")
        return path if self.studio.view_dir and os.path.isfile(path) else ""

    def file_background(self, data: dict) -> dict:
        path = self._background_file()
        if not path:
            raise PhoneError(tr("ui.phone.page.no_background_yet"))
        return _file(_jpeg(path, INPUT_SIDE), "image/jpeg")

    def _detail_file(self, image_path: str):
        """Where the picture's detail map is (cached: finding it means reading the whole picture)."""
        from ..engine.imaging import load_rgb

        try:
            key = (image_path, os.path.getmtime(image_path))
        except OSError:
            return None
        if self._detail_key != key:
            try:
                self._detail_at = details.detail_path(load_rgb(image_path))
            except OSError:
                self._detail_at = None
            self._detail_key = key
        return self._detail_at

    def _taste_counts(self) -> tuple[int, int]:
        from ..engine import aesthetic

        try:
            stamp = os.path.getmtime(aesthetic.taste_path())
        except OSError:
            stamp = None
        if self._taste_key != stamp or self._taste_value is None:
            self._taste_value, self._taste_key = aesthetic.counts(), stamp
        return self._taste_value

    def _can_continue(self, job) -> bool:
        """The shown job was interrupted and can go on (and nothing runs)."""
        view = self.studio.view_dir
        if job is not None or not view or not os.path.isdir(view):
            return False
        return jobs.summary_can_continue(jobs.job_summary(view) or {})

    def get_schema(self, data: dict) -> dict:
        """The parameters of a method as the phone shows them: groups, labels, help, limits, choices."""
        from .widgets.param_panel import param_text_key

        method = data.get("method") or self.studio.params.method()
        if method not in schema.METHODS:
            raise PhoneError("unknown method")
        groups: dict[str, list] = {}
        for p in schema.params_for(method):
            if p.kind == "path" or p.hidden:
                continue  # (a file on the computer: not from the phone; hidden: set in the app's settings)
            label_key, help_key = param_text_key(method, p.key, "label"), param_text_key(method, p.key, "help")
            item = {"key": p.key, "kind": p.kind, "label": tr(label_key) if i18n.has(label_key) else p.key,
                    "help": tr(help_key) if i18n.has(help_key) else "", "advanced": p.advanced,
                    "min": p.minimum, "max": p.maximum, "step": p.step, "decimals": p.decimals}
            if p.kind in ("choice", "flags"):
                item["choices"] = [{"value": v, "label": _choice_label(method, p, v)} for v in p.choices]
            groups.setdefault(p.group, []).append(item)
        return {"method": method,
                "groups": [{"key": g, "label": tr(f"group.{g}") if i18n.has(f"group.{g}") else g, "params": ps}
                           for g, ps in groups.items()],
                "presets": [{"key": k, "label": tr(f"ui.preset.{k}")} for k in schema.METHOD_PRESETS[method]]}

    def get_images(self, data: dict) -> dict:
        recent = [p for p in app_settings().get("recent_images") or [] if os.path.isfile(p)]
        samples = sorted(str(f) for f in paths.resource("samples").iterdir()
                         if f.suffix.lower() in (".png", ".jpg", ".jpeg"))
        return {"recent": [{"i": i, "name": os.path.basename(p)} for i, p in enumerate(recent)],
                "samples": [{"i": i, "name": os.path.splitext(os.path.basename(p))[0]} for i, p in enumerate(samples)]}

    def _image_list(self, src: str) -> list[str]:
        if src == "recent":
            return [p for p in app_settings().get("recent_images") or [] if os.path.isfile(p)]
        if src == "sample":
            return sorted(str(f) for f in paths.resource("samples").iterdir()
                          if f.suffix.lower() in (".png", ".jpg", ".jpeg"))
        raise PhoneError("unknown source")

    def _picked(self, data: dict) -> str:
        items = self._image_list(str(data.get("src", "")))
        try:
            return items[int(data.get("i", -1))]
        except (ValueError, IndexError):
            raise PhoneError(tr("ui.phone.page.no_picture")) from None

    def _all_results(self) -> list:
        """Every result of the output folder, the newest first."""
        from .pages.gallery import GalleryItem, ScanCache

        if self._cache is None:
            self._cache = ScanCache()
        items = [GalleryItem(d, s) for d, s in self._cache.scan(app_settings().get("output_dir"))]
        items = [it for it in items if it.sketch and os.path.isfile(it.sketch)]
        items.sort(key=lambda it: it.created, reverse=True)
        return items

    def _results(self) -> list:
        return self._all_results()[:RESULTS_MAX]

    def get_results(self, data: dict) -> dict:
        """A page of the results (``offset``, ``limit``), searched (``q``: name, notes, tags) and filtered by
        ``method``, ``album`` and ``fav``; with the albums and methods to filter by."""
        from . import albums

        items = self._all_results()
        q = str(data.get("q") or "").strip().lower()
        method, album = str(data.get("method") or ""), str(data.get("album") or "")
        fav = str(data.get("fav") or "") in ("1", "true")

        def keep(it) -> bool:
            return ((not method or it.method == method) and (not fav or it.favourite)
                    and (not album or album in it.albums)
                    and (not q or q in " ".join([it.name, it.notes, *it.tags]).lower()))

        shown = [it for it in items if keep(it)]
        try:
            offset = max(0, int(data.get("offset") or 0))
            limit = min(100, max(1, int(data.get("limit") or RESULTS_MAX)))
        except ValueError:
            offset, limit = 0, RESULTS_MAX
        out = []
        for k, it in enumerate(shown[offset:offset + limit]):
            out.append({"i": offset + k, "name": it.name, "method": methods_ui.name(it.method), "created": it.created,
                        "method_key": it.method, "score": round(it.score, 1) if it.score is not None else None,
                        "fav": it.favourite, "albums": it.albums, "dir": os.path.basename(it.job_dir)})
        return {"results": out, "total": len(shown), "offset": offset,
                "albums": albums.names([it.summary for it in items]),
                "methods": [{"key": m, "name": methods_ui.name(m)} for m in schema.METHODS]}

    @staticmethod
    def _not_moving(kind: str) -> None:
        """PhoneError while the results ("output") or the models ("models") move to another folder."""
        from .background import work

        if work().busy(kind):
            raise PhoneError(tr("ui.work.gallery_locked" if kind == "output" else "ui.work.models_locked"))

    def do_fav(self, data: dict) -> dict:
        from .pages.gallery import set_favourite

        self._not_moving("output")
        it = self._result({"dir": data.get("dir")})
        set_favourite(it.job_dir, bool(data.get("value")))
        if self.gallery is not None:
            self.gallery.refresh()
        return {"ok": True}

    def get_queue(self, data: dict) -> dict:
        out = []
        for j in self.controller.jobs:
            out.append({"id": j.id, "name": j.name, "status": j.status,
                        "method": methods_ui.name(j.settings.get("method", "clipasso")),
                        "progress": round(j.progress, 3)})
        return {"jobs": out}

    def _job(self, data: dict):
        try:
            job_id = int(data.get("id"))
        except (TypeError, ValueError):
            job_id = None
        job = next((j for j in self.controller.jobs if j.id == job_id), None)
        if job is None:
            raise PhoneError(tr("ui.phone.page.list_changed"))
        return job

    def do_move(self, data: dict) -> dict:
        """A waiting job to another place of the queue (dragged on the phone)."""
        job = self._job(data)
        if job.status != "queued":
            raise PhoneError(tr("ui.phone.page.list_changed"))
        try:
            index = int(data.get("index"))
        except (TypeError, ValueError):
            raise PhoneError(tr("ui.phone.page.bad_value")) from None
        self.controller.move_to(job.id, index)
        return {"ok": True}

    def do_retry(self, data: dict) -> dict:
        """A failed or cancelled job once more (it continues where it stopped when it can)."""
        if self.controller.retry(self._job(data).id) is None:
            raise PhoneError(tr("ui.phone.page.list_changed"))
        return {"ok": True}

    # ------------------------------------------------------------------ compare (the methods side by side)
    def get_compare(self, data: dict) -> dict:
        if self.compare is None:
            raise PhoneError(tr("ui.phone.page.no_studio"))
        image = self.studio.image_path if self.studio.image_path and os.path.isfile(self.studio.image_path) else ""
        overview = self.compare.overview(image)
        scored = {m: e["score"] for m, e in overview.items() if e["score"] is not None}
        best = max(scored, key=scored.get) if len(scored) > 1 else None
        return {"ok": True, "image": os.path.basename(image),
                "methods": [{"key": m, "name": methods_ui.name(m), "default": m != "scenesketch", "best": m == best,
                             "time": imaging_eta(overview[m]["seconds"]), **overview[m]} for m in schema.METHODS]}

    def do_compare(self, data: dict) -> dict:
        """The studio's picture with several methods (standard preset or the studio's settings). Questions the
        compare page asks at the computer come back as ``asks``; missing models as ``missing``."""
        s = self.studio
        if self.compare is None:
            raise PhoneError(tr("ui.phone.page.no_studio"))
        if not s.image_path or not os.path.isfile(s.image_path):
            raise PhoneError(tr("ui.phone.page.no_picture"))
        methods = [m for m in schema.METHODS if m in (data.get("methods") or [])]
        use = bool(data.get("use_studio"))
        settings = {m: self.compare._settings(m, use) for m in methods}
        missing = sorted({k for st in settings.values() for k in methods_ui.missing_models(st)})
        if missing:
            size = f"{methods_ui.download_mb(missing):.0f}"
            return {"ok": False, "missing": missing, "error": tr("ui.phone.page.models_missing", size=size)}
        asks = []
        if not methods_ui.has_cuda():
            if "controlsketch" in settings:
                answer = data.get("controlsketch_cpu")
                if answer is None:
                    asks.append({"key": "controlsketch_cpu", "text": tr("ui.compare.cpu_warning")})
                elif not answer:
                    settings.pop("controlsketch")
            if "scenesketch" in settings and not use:
                answer = data.get("scene_fast")
                if answer is None:
                    asks.append({"key": "scene_fast", "text": tr("ui.compare.scene_cpu_warning")})
                elif answer:
                    settings["scenesketch"] = schema.normalize(schema.apply_preset(settings["scenesketch"], "fast"))
        if asks:
            return {"ok": False, "asks": asks}
        if not settings:
            raise PhoneError(tr("ui.phone.page.compare_none"))
        return {"ok": True, "queued": self.compare.enqueue_compare(s.image_path, settings)}

    # ------------------------------------------------------------------ models downloaded on the phone's request
    def do_download_models(self, data: dict) -> dict:
        """Download the missing models (of the studio's settings, or ``keys``) one after the other."""
        from ..engine import model_store as store

        if self._download and self._download["status"] == "running":
            raise PhoneError(tr("ui.phone.page.download_running"))
        self._not_moving("models")
        keys = [k for k in (data.get("keys") or self.studio.params.missing_models()) if k in store.SPECS]
        keys = [k for k in keys if not store.is_available(k)]
        if not keys:
            raise PhoneError(tr("ui.phone.page.download_nothing"))
        self._download = {"keys": keys, "idx": 0, "done": 0, "total": 0, "status": "running", "error": "",
                          "cancel": False, "name": ""}
        self._next_download()
        return {"ok": True, "count": len(keys)}

    def _next_download(self):
        from ..engine import model_store as store
        from . import dialogs

        st = self._download
        if st["cancel"] or st["idx"] >= len(st["keys"]):
            st["status"] = "cancelled" if st["cancel"] else "done"
            self.studio.params._after_change()
            self.studio._update_buttons()
            if self.models_page is not None:
                self.models_page.refresh()
            return
        key = st["keys"][st["idx"]]
        st["name"], st["done"], st["total"] = dialogs.model_display_name(key), 0, 0

        def prog(a, b):
            st["done"], st["total"] = a, b

        def done(_):
            st["idx"] += 1
            self._next_download()

        def failed(msg):
            st["status"], st["error"] = ("cancelled" if st["cancel"] else "failed"), msg

        dialogs.run_in_thread(self.studio, store.install, key, cancel=lambda: st["cancel"], on_progress=prog,
                              on_done=done, on_error=failed)

    def do_cancel_download(self, data: dict) -> dict:
        if self._download:
            self._download["cancel"] = True
        return {"ok": True}

    def _download_state(self) -> dict | None:
        st = self._download
        if st is None:
            return None
        return {"status": st["status"], "name": st["name"], "index": min(st["idx"] + 1, len(st["keys"])),
                "count": len(st["keys"]), "done": st["done"], "total": st["total"], "error": st["error"]}

    # ------------------------------------------------------------------ the picture: crop / rotate, the mask
    def do_crop(self, data: dict) -> dict:
        """Crop (normalised ``x``, ``y``, ``w``, ``h`` of the turned picture), turn (``rotate``: 0/90/180/270,
        clockwise) and mirror (``flip``) the studio's picture – saved as a new file, like the studio's editor."""
        import time

        from PySide6.QtCore import QRect
        from PySide6.QtGui import QTransform

        from .image_io import read_image

        s = self.studio
        if not s.image_path or not os.path.isfile(s.image_path):
            raise PhoneError(tr("ui.phone.page.no_picture"))
        try:
            rotate = int(data.get("rotate") or 0) % 360
            x, y, w, h = (min(1.0, max(0.0, float(data.get(k, d)))) for k, d in
                          (("x", 0), ("y", 0), ("w", 1), ("h", 1)))
        except (TypeError, ValueError):
            raise PhoneError(tr("ui.phone.page.bad_value")) from None
        if rotate not in (0, 90, 180, 270):
            raise PhoneError(tr("ui.phone.page.bad_value"))
        img = read_image(s.image_path)
        if img.isNull():
            raise PhoneError(tr("ui.phone.page.no_picture"))
        if rotate:
            img = img.transformed(QTransform().rotate(rotate))
        if data.get("flip"):
            img = img.mirrored(True, False)
        rect = QRect(round(x * img.width()), round(y * img.height()), round(w * img.width()),
                     round(h * img.height())).intersected(img.rect())
        if rect.width() < 16 or rect.height() < 16:
            raise PhoneError(tr("ui.phone.page.crop_small"))
        folder = os.path.join(app_settings().get("output_dir"), "_edited")
        os.makedirs(folder, exist_ok=True)
        stem = os.path.splitext(os.path.basename(s.image_path))[0]
        path = os.path.join(folder, f"{stem}-edited-{time.strftime('%Y%m%d-%H%M%S')}.png")
        if not img.copy(rect).save(path):
            raise PhoneError(tr("ui.phone.page.failed"))
        s.set_image(path)
        return {"ok": True}

    def _mask_state(self) -> dict:
        s = self.studio
        used = s._mask_settings()[0] and bool(s.image_path)
        return {"used": used, "ready": used and s._mask is not None, "text": s.mask_status.text() if used else ""}

    def file_mask(self, data: dict) -> dict:
        """The studio's picture with its mask: the background veiled, the object outlined (as in the studio)."""
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QColor, QPainter

        from ..engine import masking
        from . import mask_view, theme
        from .image_io import read_image

        s = self.studio
        if not self._mask_state()["ready"]:
            raise PhoneError(tr("ui.phone.page.mask_not_ready"))
        _, model, _ = s._mask_settings()
        _, prob, edited = mask_view.load_mask(s.image_path, model)
        if prob is None and edited is None:
            raise PhoneError(tr("ui.phone.page.mask_not_ready"))
        mask = edited if edited is not None else prob >= masking.OBJECT_THRESHOLD
        photo = read_image(s.image_path, INPUT_SIDE)
        pal = theme.current()
        veil = QColor(pal.surface2)
        veil.setAlpha(215)
        over = mask_view.overlay(mask, veil, QColor(pal.accent), max_side=INPUT_SIDE)
        p = QPainter(photo)
        p.drawImage(photo.rect(), over)
        p.end()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        photo.save(buf, "JPEG", 85)
        return _file(bytes(buf.data()), "image/jpeg")

    # ------------------------------------------------------------------ files
    def file_input(self, data: dict) -> dict:
        s = self.studio
        if not s.image_path or not os.path.isfile(s.image_path):
            raise PhoneError(tr("ui.phone.page.no_picture"))
        return _file(_jpeg(s.image_path, INPUT_SIDE), "image/jpeg")

    def file_image(self, data: dict) -> dict:
        return _file(_jpeg(self._picked(data), 240), "image/jpeg")

    def _seed_svg(self, data: dict) -> tuple[int, str]:
        s = self.studio
        try:
            seed = int(data.get("seed")) if data.get("seed") not in (None, "") else None
        except ValueError:
            seed = None
        if seed is None:
            seed = s.selected_seed if s.selected_seed is not None else s.best_seed
        svg = s.seed_svgs.get(seed)
        if not svg:
            raise PhoneError(tr("ui.phone.page.no_sketch"))
        return seed, svg

    def _look(self) -> tuple[str, dict | None, str]:
        """The studio's brush style, paper and background colour."""
        from . import brush
        from . import paper as paper_mod

        st = app_settings()
        style = st.get("canvas_style", "plain")
        kind = st.get("canvas_paper", "none")
        paper = {"kind": kind, "vignette": paper_mod.VIGNETTE if st.get("canvas_vignette") else 0.0} \
            if kind in paper_mod.KINDS and kind != "none" else None
        background = paper_mod.color_of({"kind": kind}, st.get("canvas_paper_color") or None) \
            if paper is not None or st.get("canvas_paper_color") else "#FFFFFF"
        return (style if style in brush.STYLES else "plain"), paper, background

    def file_sketch(self, data: dict) -> dict:
        """A sketch of the shown job as the studio shows it: in its brush style (``full``: on its paper, too)."""
        from . import brush
        from . import paper as paper_mod
        from .export import restyle_svg

        style, paper, background = self._look()
        seed, svg = self._seed_svg(data)
        if data.get("part") in ("background", "object") and self.studio.layers_available(seed):
            from . import scene_layers  # (SceneSketch: only the background or only the object of the cell)

            svg = scene_layers.part(svg, self.studio.seed_runs.get(seed), data["part"])
        svg = brush.stylize_svg(restyle_svg(svg, None, 1.0, background), style)
        if data.get("full") and paper is not None:
            svg = paper_mod.svg_with_paper(svg, paper, background)
        return _file(svg.encode("utf-8"), "image/svg+xml")

    def file_result(self, data: dict) -> dict:
        if data.get("d") and "i" not in data:  # (by its folder name)
            it = self._result({"dir": data["d"]})
        else:
            items = self._results()
            try:
                it = items[int(data.get("i", -1))]
            except (ValueError, IndexError):
                raise PhoneError(tr("ui.phone.page.no_sketch")) from None
        with open(it.sketch, encoding="utf-8") as f:
            return _file(f.read().encode("utf-8"), "image/svg+xml")

    def file_download(self, data: dict) -> dict:
        """The shown sketch as SVG or PNG (in the studio's brush style and on its paper)."""
        import tempfile

        from . import export

        s = self.studio
        seed, svg = self._seed_svg(data)
        run_dir = s.seed_runs.get(seed)
        stem = os.path.basename(os.path.normpath(run_dir)) if run_dir else f"sketch_{seed}"
        style, paper, background = self._look()
        fmt = data.get("fmt", "svg")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.svg")
            with open(src, "w", encoding="utf-8") as f:
                f.write(svg)
            if fmt == "png":
                dest = os.path.join(tmp, "out.png")
                export.export_png(src, dest, size=int(data.get("size") or 1600), background=background,
                                  style=style, paper=paper)
                ctype = "image/png"
            else:
                fmt = "svg"
                dest = os.path.join(tmp, "out.svg")
                export.export_svg(src, dest, background=background, style=style, paper=paper)
                ctype = "image/svg+xml"
            with open(dest, "rb") as f:
                return _file(f.read(), ctype, f"{stem}.{fmt}")

    # ------------------------------------------------------------------ export (all the formats of the studio)
    def _shown_seed(self):
        s = self.studio
        return s.selected_seed if s.selected_seed is not None else s.best_seed

    def _export_source(self, fmt: str) -> tuple[str, str, str]:
        """(sketch file, run folder – the job folder for the matrix –, name) of the shown sketch."""
        s = self.studio
        if fmt == "matrix":
            if not s._matrix_exportable():
                raise PhoneError(tr("ui.phone.page.no_sketch"))
            sel = s._selected_run()
            return (sel[0] if sel else ""), s.view_dir, os.path.basename(os.path.normpath(s.view_dir))
        sel = s._selected_run()
        if not sel:
            raise PhoneError(tr("ui.phone.page.no_sketch"))
        svg, run_dir = sel
        return svg, run_dir, os.path.basename(os.path.normpath(run_dir))

    def get_export_info(self, data: dict) -> dict:
        """The formats with their options (which apply, the remembered choices) for the shown sketch."""
        from . import brush
        from . import paper as paper_mod
        from ..engine import framing

        svg, run_dir, name = self._export_source("svg")
        sketch = export_jobs.info(svg, run_dir)
        formats = [f for f in export_jobs.FORMATS if (f != "matrix" or self.studio._matrix_exportable())
                   and (f != "svglayers" or self.studio.layers_available(self._shown_seed()))]
        return {"ok": True, "name": name, "sketch": sketch,
                "formats": [{"fmt": f, "title": export_jobs.title(f), "desc": tr(f"ui.export_desc.{f}"),
                             "ext": export_jobs.extension(f),
                             "applies": export_jobs.applies(f, sketch["process_frames"]),
                             "defaults": export_jobs.defaults(f, sketch)} for f in formats],
                "styles": [{"key": k, "label": tr(f"ui.brush.{k}")} for k in brush.STYLES],
                "papers": [{"key": k, "label": tr(f"ui.paper.{k}")} for k in paper_mod.KINDS],
                "frames": [{"key": k, "label": tr(f"ui.frame.{k}"), "ok": k != "photo" or sketch["photo_frame"]}
                           for k in framing.MODES],
                "last": app_settings().get("export_last_format", "png")}

    def _clean_exports(self, keep: int = 3):
        """Older exports go (the files of the last few stay to be downloaded)."""
        import shutil

        done = sorted((e for e in self._exports.values() if e["status"] != "running"), key=lambda e: e["started"])
        for e in done[:-keep] if keep else done:
            shutil.rmtree(e["dir"], ignore_errors=True)
            self._exports.pop(e["id"], None)
        root = self.export_root()
        if os.path.isdir(root):  # (left from an earlier start of the app)
            for name in os.listdir(root):
                if name not in self._exports:
                    shutil.rmtree(os.path.join(root, name), ignore_errors=True)

    def do_export(self, data: dict) -> dict:
        """Start an export of the shown sketch (in the background); the phone asks for its state and then
        downloads it."""
        import secrets
        import time

        from . import dialogs

        fmt = data.get("fmt")
        if fmt not in export_jobs.FORMATS:
            raise PhoneError("unknown format")
        if fmt == "svglayers" and not self.studio.layers_available(self._shown_seed()):
            raise PhoneError(tr("ui.layer.not_yet"))
        svg, run_dir, name = self._export_source(fmt)
        sketch = export_jobs.info(svg, run_dir) if svg else {"process_frames": 0, "draw_length": 2.0,
                                                              "process_length": 2.0, "photo_frame": False}
        options = export_jobs.check(fmt, data.get("options"), sketch)
        export_jobs.remember(fmt, options)
        self._clean_exports()
        job_id = secrets.token_hex(6)
        folder = os.path.join(self.export_root(), job_id)
        os.makedirs(folder, exist_ok=True)
        file_name = f"{name}{export_jobs.SUFFIX.get(fmt, '')}.{export_jobs.extension(fmt)}"
        entry = {"id": job_id, "fmt": fmt, "status": "running", "done": 0, "total": 0, "name": file_name,
                 "path": os.path.join(folder, file_name), "dir": folder, "error": "", "cancel": False,
                 "started": time.time()}
        self._exports[job_id] = entry

        def work(progress=None):
            return export_jobs.run(fmt, svg, run_dir, entry["path"], options, progress=progress,
                                   cancel=lambda: entry["cancel"])

        def prog(a, b):
            entry["done"], entry["total"] = a, b

        def done(_):
            entry["status"] = "cancelled" if entry["cancel"] else (
                "done" if os.path.isfile(entry["path"]) else "failed")

        def failed(msg):
            entry["status"], entry["error"] = ("cancelled" if entry["cancel"] else "failed"), msg

        dialogs.run_in_thread(self.studio, work, on_progress=prog, on_done=done, on_error=failed)
        return {"ok": True, "id": job_id, "name": file_name}

    def _export(self, data: dict) -> dict:
        entry = self._exports.get(str(data.get("id", "")))
        if entry is None:
            raise PhoneError(tr("ui.phone.page.export_gone"))
        return entry

    def get_export(self, data: dict) -> dict:
        e = self._export(data)
        size = os.path.getsize(e["path"]) if e["status"] == "done" and os.path.isfile(e["path"]) else 0
        return {"ok": True, "status": e["status"], "done": e["done"], "total": e["total"], "name": e["name"],
                "size": size, "error": e["error"]}

    def file_export(self, data: dict) -> dict:
        """The finished file (sent from the disk by the server)."""
        e = self._export(data)
        if e["status"] != "done" or not os.path.isfile(e["path"]):
            raise PhoneError(tr("ui.phone.page.export_gone"))
        ext = export_jobs.extension(e["fmt"])
        return {"_path": e["path"], "_type": export_jobs.CONTENT_TYPES.get(ext, "application/octet-stream"),
                "_name": e["name"]}

    def do_cancel_export(self, data: dict) -> dict:
        e = self._export(data)
        e["cancel"] = True
        return {"ok": True}

    @staticmethod
    def export_root() -> str:
        return str(paths.user_data_dir() / "phone_exports")

    # ------------------------------------------------------------------ own presets
    def do_user_preset(self, data: dict) -> dict:
        """An own preset (of any method: the studio switches to it)."""
        if not self.studio.params.apply_user_preset(str(data.get("name", "")), str(data.get("method", ""))):
            raise PhoneError(tr("ui.phone.page.preset_gone"))
        return {"ok": True}

    def do_save_preset(self, data: dict) -> dict:
        name = self.studio.params.save_user_preset(str(data.get("name", "")))
        if not name:
            raise PhoneError(tr("ui.phone.page.bad_value"))
        return {"ok": True, "name": name}

    def do_delete_preset(self, data: dict) -> dict:
        if not user_presets.delete(str(data.get("name", "")), str(data.get("method", ""))):
            raise PhoneError(tr("ui.phone.page.preset_gone"))
        self.studio.params._detect_preset()
        return {"ok": True}

    def file_details(self, data: dict) -> dict:
        """The detail map at the size of ``file_input`` (8-bit grey, 128 normal) – to paint on."""
        from PIL import Image

        from ..engine.imaging import load_rgb

        s = self.studio
        if not s.image_path:
            raise PhoneError(tr("ui.phone.page.no_picture"))
        im = load_rgb(s.image_path)
        w, h = im.size
        scale = min(1.0, INPUT_SIDE / max(w, h))
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        values = details.detail_map(im)
        arr = np.full((h, w), details.NORMAL, np.uint8) if values is None else \
            np.clip(np.round(details.NORMAL + values * 127), 0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(arr, mode="L").resize(size, Image.BILINEAR).save(buf, "PNG")
        return _file(buf.getvalue(), "image/png")

    # ------------------------------------------------------------------ changes
    def do_set(self, data: dict) -> dict:
        s = self.studio
        key = data.get("key")
        p = next((q for q in schema.params_for(s.params.method()) if q.key == key), None)
        if p is None or p.kind == "path" or key not in s.params.fields:
            raise PhoneError("unknown setting")
        try:
            value = schema.coerce(p, data.get("value"))
        except (TypeError, ValueError):
            raise PhoneError(tr("ui.phone.page.bad_value")) from None
        s.params.no_dialogs = True  # (SDXL on a small card: piece by piece, without asking at the computer)
        try:
            s.params.fields[key].set_value(value, emit=True)
        finally:
            s.params.no_dialogs = False
        return {"ok": True}

    def do_method(self, data: dict) -> dict:
        method = data.get("method")
        if method not in schema.METHODS:
            raise PhoneError("unknown method")
        self.studio.params.set_method(method)
        return {"ok": True}

    def do_preset(self, data: dict) -> dict:
        name = data.get("preset")
        if name not in schema.METHOD_PRESETS[self.studio.params.method()]:
            raise PhoneError("unknown preset")
        self.studio.params.apply_preset(name)
        return {"ok": True}

    def do_reset(self, data: dict) -> dict:
        self.studio.params.reset_all_fields()
        return {"ok": True}

    def do_budget(self, data: dict) -> dict:
        try:
            minutes = max(1, min(int(float(data.get("minutes", 0))), 24 * 60))
        except (TypeError, ValueError):
            raise PhoneError(tr("ui.phone.page.bad_value")) from None
        self.studio.fit_to_budget(minutes)
        return {"ok": True, "estimate": self.studio.estimate.text()}

    def do_style(self, data: dict) -> dict:
        from . import brush
        from . import paper as paper_mod

        if data.get("style") in brush.STYLES:
            self.studio.set_canvas_style(data["style"])
        if data.get("paper") in paper_mod.KINDS:
            self.studio.set_canvas_paper(kind=data["paper"])
        return {"ok": True}

    def do_image(self, data: dict) -> dict:
        """A recent picture or a sample becomes the studio's input."""
        self.studio.set_image(self._picked(data))
        return {"ok": True}

    def set_image(self, path: str) -> dict:
        """A picture from the phone (uploaded) becomes the studio's input."""
        self.studio.set_image(path)
        if self.link is not None:
            self.link.toast.emit(tr("ui.phone.received", name=os.path.basename(path)), "success")
        return {"ok": True}

    def do_start(self, data: dict) -> dict:
        """Start (or queue) the studio's picture with its settings. Memory short: the phone asks (``ask``) and
        sends ``memory`` = "smaller" or "anyway"."""
        from . import resources

        s = self.studio
        if not s.image_path or not os.path.isfile(s.image_path):
            raise PhoneError(tr("ui.phone.page.no_picture"))
        missing = s.params.missing_models()
        if missing:
            raise PhoneError(tr("ui.phone.page.models_missing", size=f"{methods_ui.download_mb(missing):.0f}"))
        s.params._after_change()
        settings = s.params.settings()
        short = resources.shortage(settings)
        if short is not None:
            text, changes = short
            if data.get("memory") == "smaller" and changes:
                settings = {**settings, **changes}
                s.params.set_settings(settings)
                settings = s.params.settings()
            elif data.get("memory") != "anyway":
                return {"ok": False, "ask": {"text": text, "smaller": resources.describe(changes) if changes else ""}}
        queue = bool(data.get("queue"))
        busy = self.controller.is_busy()
        self.controller.enqueue(s.image_path, settings, start=not busy if queue else True)
        return {"ok": True, "queued": busy}

    def do_select(self, data: dict) -> dict:
        try:
            seed = int(data.get("seed"))
        except (TypeError, ValueError):
            raise PhoneError("unknown sketch") from None
        if seed not in self.studio.seed_svgs:
            raise PhoneError(tr("ui.phone.page.no_sketch"))
        self.studio.select_seed(seed)
        return {"ok": True}

    def do_rate(self, data: dict) -> dict:
        value = data.get("value")
        if value not in (1, -1):
            raise PhoneError(tr("ui.phone.page.bad_value"))
        if not self.studio.rate_sketch(value):
            raise PhoneError(tr("ui.phone.page.no_sketch"))
        return {"ok": True}

    def _result(self, data: dict):
        """A result by its folder name – or by its place in the list of the newest and its folder name, so a list
        that changed meanwhile never hits another one."""
        if "i" not in data:
            name = str(data.get("dir") or "")
            it = next((x for x in self._all_results() if os.path.basename(os.path.normpath(x.job_dir)) == name),
                      None) if name else None
            if it is None:
                raise PhoneError(tr("ui.phone.page.list_changed"))
            return it
        items = self._results()
        try:
            it = items[int(data.get("i", -1))]
        except (ValueError, IndexError):
            raise PhoneError(tr("ui.phone.page.no_sketch")) from None
        if data.get("dir") and data["dir"] != os.path.basename(os.path.normpath(it.job_dir)):
            raise PhoneError(tr("ui.phone.page.list_changed"))
        return it

    def do_open(self, data: dict) -> dict:
        """A recent result is shown in the studio (its sketches, picture and settings)."""
        self.studio.show_job_dir(self._result(data).job_dir)
        return {"ok": True}

    def do_delete(self, data: dict) -> dict:
        """A result goes to the recycle bin (the gallery's own way; never a job the queue works on)."""
        import shutil

        self._not_moving("output")
        it = self._result(data)
        name = os.path.basename(os.path.normpath(it.job_dir))
        if os.path.normcase(os.path.abspath(it.job_dir)) in self.controller.active_dirs():
            raise PhoneError(tr("ui.gallery.delete_active", name=name))
        if self.gallery is not None:
            ok = self.gallery.delete_job(it.job_dir, confirm=False)
        else:
            from .pages.other_pages import move_to_trash

            ok = move_to_trash(it.job_dir)
            if not ok:
                shutil.rmtree(it.job_dir, ignore_errors=True)
                ok = not os.path.exists(it.job_dir)
            if ok:
                self.studio.forget_job_dir(it.job_dir)
        if not ok:
            raise PhoneError(tr("ui.phone.page.not_deleted", name=name))
        return {"ok": True}

    def do_live(self, data: dict) -> dict:
        """Back to the running job (after a result of the gallery was opened during the run)."""
        if not self.controller.is_busy():
            raise PhoneError(tr("ui.phone.page.no_live"))
        self.studio.show_running_job()
        return {"ok": True}

    def do_clear_queue(self, data: dict) -> dict:
        """The finished, cancelled and failed jobs leave the queue (the waiting and running ones stay)."""
        before = len(self.controller.jobs)
        self.controller.clear_finished()
        return {"ok": True, "removed": before - len(self.controller.jobs)}

    def do_remove(self, data: dict) -> dict:
        """A waiting job leaves the queue."""
        try:
            job_id = int(data.get("id"))
        except (TypeError, ValueError):
            raise PhoneError("unknown job") from None
        self.controller.remove(job_id)
        return {"ok": True}

    def do_continue(self, data: dict) -> dict:
        """The shown, interrupted job goes on."""
        s = self.studio
        if not s.view_dir or s.controller.continue_job(s.view_dir) is None:
            raise PhoneError(tr("ui.phone.page.cannot_continue"))
        return {"ok": True}

    # ------------------------------------------------------------------ the detail brush
    def set_details(self, png: bytes) -> dict:
        """The map painted on the phone (grey PNG at the size of ``file_input``): scaled to the picture and kept."""
        from PIL import Image

        from ..engine.imaging import load_rgb

        s = self.studio
        if not s.image_path:
            raise PhoneError(tr("ui.phone.page.no_picture"))
        im = load_rgb(s.image_path)
        with Image.open(io.BytesIO(png)) as m:
            full = np.asarray(m.convert("L").resize(im.size, Image.BILINEAR))
        details.save_detail_map(im, full)
        self._details_changed()
        return {"ok": True}

    def do_clear_details(self, data: dict) -> dict:
        from ..engine.imaging import load_rgb

        s = self.studio
        if s.image_path:
            details.remove_detail_map(load_rgb(s.image_path))
        self._details_changed()
        return {"ok": True}

    def do_face(self, data: dict) -> dict:
        """Portrait mode: find the face (in the background) and mark its eyes, nose and mouth "more"."""
        from . import dialogs, portrait
        from ..engine.imaging import load_rgb

        s = self.studio
        if not s.image_path:
            raise PhoneError(tr("ui.phone.page.no_picture"))
        if not model_store.is_available(portrait.KEY):
            raise PhoneError(tr("ui.phone.page.models_missing", size="0.4"))
        path = s.image_path

        def find(progress=None):
            im = load_rgb(path)
            photo = im.copy()
            photo.thumbnail((1024, 1024))
            values = portrait.detect(photo)
            if values is None:
                return False
            from PIL import Image

            more = np.asarray(Image.fromarray(values, mode="L").resize(im.size, Image.BILINEAR))
            old = details.detail_map(im)
            if old is not None:
                old_u8 = np.clip(np.round(details.NORMAL + old * 127), 0, 255).astype(np.uint8)
                more = np.maximum(more, old_u8)
            details.save_detail_map(im, more)
            return True

        def done(found):
            self._details_changed()
            self._say(tr("ui.phone.page.face_found") if found else tr("ui.detail.no_face"))

        dialogs.run_in_thread(s, find, on_done=done, on_error=lambda msg: self._say(msg))
        return {"ok": True, "busy": True}

    def _details_changed(self):
        self._details_rev += 1
        self.studio._update_detail_button()
