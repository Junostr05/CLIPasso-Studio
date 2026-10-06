"""Exports with their options as plain data – what the export dialog of the studio offers, for the phone page: the
formats, which option applies to which, the remembered choices (shared with the dialog), checking what the phone
sends, and the export itself (in a background thread, with progress and cancel for the animations)."""

from __future__ import annotations

import os

from ..engine import framing
from . import brush, export
from . import paper as paper_mod
from .app_settings import app_settings
from .i18n import tr

FORMATS = ("png", "svg", "svg1", "svglayers", "pdf", "gif", "mp4", "webp", "svganim", "lottie", "html", "matrix")
ANIMATIONS = ("gif", "mp4", "webp")  # the drawing process or stroke by stroke, rendered frame by frame
DRAWN = ("svganim", "lottie", "html")  # the finished strokes drawn one by one by the viewer
TIMED = ANIMATIONS + DRAWN
EXTENSIONS = {"svg1": "svg", "svglayers": "svg", "matrix": "zip", "svganim": "svg", "lottie": "json", "html": "html"}
SUFFIX = {"svg1": "_1layer", "svglayers": "_layers", "matrix": "_matrix", "svganim": "_animated"}
TRANSPARENT_OK = ("svg", "svglayers", "png", "webp", "matrix", "svganim", "pdf", "lottie")
CONTENT_TYPES = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf", "gif": "image/gif",
                 "mp4": "video/mp4", "webp": "image/webp", "json": "application/json",
                 "html": "application/octet-stream", "zip": "application/zip"}  # (a page only to save, not to open)
MAX_SIZE = 4096  # px – from the phone (the computer's dialog goes to 8192)


def extension(fmt: str) -> str:
    return EXTENSIONS.get(fmt, fmt)


def title(fmt: str) -> str:
    return {"svg1": tr("ui.export_svg1"), "svglayers": tr("ui.export_svglayers"), "webp": "WebP",
            "matrix": tr("ui.export_matrix"),
            "svganim": tr("ui.export_svganim"), "lottie": "Lottie", "html": tr("ui.export_html")}.get(fmt, fmt.upper())


def applies(fmt: str, process_frames: int = 0) -> dict:
    """Which options the format has (like the export dialog)."""
    return {"stroke": True, "width": True, "style": fmt not in ("svg1", "lottie"),
            "background": fmt != "svg1", "transparent": fmt in TRANSPARENT_OK, "paper": fmt != "svg1",
            "frame": fmt != "matrix",
            "size": fmt not in ("svg", "svg1", "svglayers", "svganim", "pdf", "lottie", "html"),
            "width_cm": fmt == "pdf",
            "mode": fmt in ANIMATIONS and process_frames > 1, "length": fmt in TIMED, "hold": fmt in TIMED}


def info(svg_path: str, run_dir: str) -> dict:
    """What the sketch offers for the animations: saved steps of the drawing process, strokes, a drawing length."""
    from .dialogs import _stroke_count, default_animation_length

    frames = len(export.animation_frames(run_dir)) if run_dir else 0
    return {"process_frames": frames, "strokes": _stroke_count(svg_path),
            "draw_length": round(export.drawing_length(svg_path), 1),
            "process_length": default_animation_length(frames),
            "photo_frame": _photo_frame_known(svg_path)}


def _photo_frame_known(svg_path: str) -> bool:
    try:
        return export.framing_for(svg_path, "photo") is not None
    except Exception:
        return False


def defaults(fmt: str, sketch: dict) -> dict:
    """The options the dialog would start with (the choices of the last export, shared with the phone)."""
    st = app_settings()
    bg = st.get("export_background") or ("#FFFFFF" if fmt not in ("svg", "svglayers", "svganim", "lottie")
                                         else "transparent")
    if bg == "transparent" and fmt not in TRANSPARENT_OK:
        bg = "#FFFFFF"
    frame = st.get("export_frame", "square")
    if frame not in framing.MODES or (frame == "photo" and not sketch.get("photo_frame")):
        frame = "square"
    mode = "strokes" if fmt in DRAWN or sketch.get("process_frames", 0) < 2 else st.get("export_anim_mode", "process")
    length = sketch["draw_length"] if mode == "strokes" or fmt in DRAWN else sketch["process_length"]
    return {"stroke": str(st.get("export_stroke", "#000000") or "#000000"),
            "width": _number(st.get("export_width", 1.0), 1.0), "style": st.get("export_style", "plain"),
            "background": bg, "paper": st.get("export_paper", "none"),
            "vignette": int(_number(st.get("export_vignette", 0), 0)), "frame": frame,
            "margin": int(_number(st.get("export_margin", 5), 5)),
            "size": 1024 if fmt in ("png", "matrix") else 512,
            "width_cm": _number(st.get("export_pdf_width", export.PDF_WIDTH_CM), export.PDF_WIDTH_CM),
            "mode": mode, "length": max(0.5, length), "hold": 1.0}


def _number(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _colour(value, fallback: str, transparent: bool = False) -> str:
    text = str(value or "").strip()
    if transparent and text == "transparent":
        return text
    if len(text) == 7 and text[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in text[1:]):
        return text
    return fallback


def check(fmt: str, raw: dict, sketch: dict) -> dict:
    """The options the phone sent, made safe (unknown values fall back to the defaults, numbers are clamped)."""
    if fmt not in FORMATS:
        raise ValueError(fmt)
    base = defaults(fmt, sketch)
    ok = applies(fmt, sketch.get("process_frames", 0))
    raw = raw if isinstance(raw, dict) else {}

    def clamp(key, lo, hi, cast=float):
        return cast(min(hi, max(lo, _number(raw.get(key, base[key]), base[key]))))

    out = dict(base)
    out["stroke"] = _colour(raw.get("stroke"), base["stroke"])
    out["width"] = clamp("width", 0.1, 10.0)
    out["style"] = raw.get("style") if raw.get("style") in brush.STYLES else base["style"]
    out["background"] = _colour(raw.get("background"), base["background"], transparent=ok["transparent"])
    out["paper"] = raw.get("paper") if raw.get("paper") in paper_mod.KINDS else base["paper"]
    out["vignette"] = clamp("vignette", 0, 100, int)
    frame = raw.get("frame")
    out["frame"] = frame if frame in framing.MODES and (frame != "photo" or sketch.get("photo_frame")) else "square"
    out["margin"] = clamp("margin", 0, 50, int)
    out["size"] = clamp("size", 64, MAX_SIZE, int)
    out["width_cm"] = clamp("width_cm", 2.0, 200.0)
    out["mode"] = raw.get("mode") if ok["mode"] and raw.get("mode") in ("process", "strokes") else (
        "strokes" if not ok["mode"] else base["mode"])
    out["length"] = clamp("length", 0.5, 300.0)
    out["hold"] = clamp("hold", 0.0, 10.0)
    return out


def remember(fmt: str, o: dict) -> None:
    """Keep the choices for the next export (the dialog of the computer starts with them, too)."""
    st = app_settings()
    st.data.update(export_last_format=fmt, export_stroke=o["stroke"], export_width=o["width"])
    if fmt != "svg1":
        st.data.update(export_style=o["style"], export_background=o["background"], export_paper=o["paper"],
                       export_vignette=o["vignette"])
    if fmt != "matrix":
        st.data.update(export_frame=o["frame"], export_margin=o["margin"])
    if fmt == "pdf":
        st.data["export_pdf_width"] = o["width_cm"]
    if fmt in ANIMATIONS:
        st.data["export_anim_mode"] = o["mode"]
    st.save()


def run(fmt: str, svg_path: str, run_dir: str, dest: str, o: dict, progress=None, cancel=None) -> str:
    """Export (in the calling thread – a background one for anything big). ``run_dir`` is the job folder for the
    SceneSketch matrix. Returns ``dest``; cancelled: ``InterruptedError`` (or ``dest`` missing)."""
    stroke = None if o["stroke"].lower() == "#000000" else o["stroke"]
    bg = None if o["background"] == "transparent" else o["background"]
    style = o["style"] if fmt not in ("svg1", "lottie") else "plain"
    pp = paper_mod.normalize({"kind": o["paper"], "vignette": o["vignette"] / 100}) if fmt != "svg1" else None
    shape = {"frame": o["frame"], "margin": o["margin"] / 100} if fmt != "matrix" else {}
    width = o["width"]
    try:
        if fmt in ("svg", "svglayers"):
            write = export.export_svg if fmt == "svg" else export.export_layered_svg
            write(svg_path, dest, stroke, width, bg, style, **shape, paper=pp)
        elif fmt == "svg1":
            export.export_single_layer_svg(svg_path, dest, stroke, width, **shape)
        elif fmt == "png":
            export.export_png(svg_path, dest, o["size"], stroke, width, bg, style, **shape, paper=pp)
        elif fmt == "pdf":
            export.export_pdf(svg_path, dest, o["width_cm"], stroke, width, bg, style, **shape, paper=pp)
        elif fmt == "lottie":
            export.export_lottie(svg_path, dest, o["length"], o["hold"], stroke, width, bg, **shape, paper=pp)
        elif fmt == "html":
            export.export_web_page(svg_path, dest, o["length"], o["hold"], stroke, width, bg, style, **shape, paper=pp)
        elif fmt == "svganim":
            export.export_animated_svg(svg_path, dest, o["length"], o["hold"], stroke, width, bg, style, **shape,
                                       paper=pp)
        else:
            common = {"size": o["size"], "stroke_color": stroke, "width_scale": width, "background": bg, "style": style,
                      "paper": pp, "progress": progress, "cancel": cancel}
            if fmt == "matrix":
                export.export_matrix_zip(run_dir, dest, **common)
            elif o["mode"] == "strokes":
                export.export_drawing(svg_path, dest, length=o["length"], hold=o["hold"], **common, **shape)
            else:
                export.export_animation(run_dir, dest, length=o["length"], hold=o["hold"], **common, **shape)
    except InterruptedError:  # (cancelled: no half file is left)
        _remove(dest)
        raise
    if cancel is not None and cancel():
        _remove(dest)
    return dest


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
