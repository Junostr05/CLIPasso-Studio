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
from . import methods_ui
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
        self.gallery = None  # the gallery page (deleting goes its way), set by the main window
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
    def get_studio(self, data: dict) -> dict:
        s = self.studio
        c = self.controller
        method = s.params.method()
        settings = s.params.settings()
        params = [p for p in schema.params_for(method) if p.kind != "path"]
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
        }

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
            if p.kind == "path":
                continue  # (a file on the computer: not from the phone)
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

    def _results(self) -> list:
        from .pages.gallery import GalleryItem, ScanCache

        if self._cache is None:
            self._cache = ScanCache()
        items = [GalleryItem(d, s) for d, s in self._cache.scan(app_settings().get("output_dir"))]
        items = [it for it in items if it.sketch and os.path.isfile(it.sketch)]
        items.sort(key=lambda it: it.created, reverse=True)
        return items[:RESULTS_MAX]

    def get_results(self, data: dict) -> dict:
        out = []
        for i, it in enumerate(self._results()):
            out.append({"i": i, "name": it.name, "method": methods_ui.name(it.method), "created": it.created,
                        "score": round(it.score, 1) if it.score is not None else None, "fav": it.favourite,
                        "dir": os.path.basename(it.job_dir)})
        return {"results": out}

    def get_queue(self, data: dict) -> dict:
        out = []
        for j in self.controller.jobs:
            out.append({"id": j.id, "name": j.name, "status": j.status,
                        "method": methods_ui.name(j.settings.get("method", "clipasso")),
                        "progress": round(j.progress, 3)})
        return {"jobs": out}

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
        svg = brush.stylize_svg(restyle_svg(self._seed_svg(data)[1], None, 1.0, background), style)
        if data.get("full") and paper is not None:
            svg = paper_mod.svg_with_paper(svg, paper, background)
        return _file(svg.encode("utf-8"), "image/svg+xml")

    def file_result(self, data: dict) -> dict:
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
        """A recent result by its place in the list – and its folder name, so a list that changed meanwhile never
        hits another one."""
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
