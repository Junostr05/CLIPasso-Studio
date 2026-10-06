"""Persistent application preferences (language, theme, folders, last parameters …)."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .. import paths

# 2: "language" defaults to "auto" (2.0.1)
SETTINGS_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "tour_done": False,  # the first-start guide was shown
    "settings_version": SETTINGS_VERSION,
    "language": "auto",
    "theme": "dark",
    "output_dir": str(paths.default_output_dir()),
    "keep_awake": True,
    "notify": True,
    "check_updates": True,
    "ui_scale": 1.0,  # interface size (applied at the start via QT_SCALE_FACTOR)
    "canvas_style": "plain",  # brush style the sketches are shown in (brush.STYLES)
    "canvas_paper": "none",  # paper of the preview (paper.KINDS); the export starts with it
    "canvas_paper_color": "",  # its colour ("": the paper's own colour)
    "canvas_vignette": False,
    "recent_images": [],  # the last opened images (studio menu "recent")
    "webcam_mirror": True,
    "watch_enabled": False,  # watched folder (gui/watch.py)
    "watch_folder": "",
    "watch_preset": "studio",  # "studio": the current studio settings, else a preset file
    "watch_formats": ["png"],
    "watch_export_dir": "",  # "": a subfolder "sketches" of the watched folder
    "watch_move_done": False,
    "keep_models_loaded": True,  # the worker stays open between jobs with its models (runner keep_warm)
    "parallel_sketches": "auto",  # "auto": the sketches of a job in parallel on a big CPU (runner.plan_workers)
    "gpu_runtime": "",  # the PyTorch for older graphics cards that is switched on (gpu_runtime.py), "" = off
    "gpu_runtime_dismissed": "",  # its offer was declined ("don't ask again") for this runtime
    "gpu_precision": "auto",  # "auto": float16 for the big networks on the GPU, "fp32": always full precision
    "sdxl_small_gpu": "",  # SDXL chosen on a card with less than 8 GB: "" ask, "cpu" on the CPU, "clip" use CLIP
    "multi_gpu": True,  # with two or more graphics cards: one sketch worker per card (runner.spreads_over_gpus)
    "resource_check": True,  # ask before a job that may not fit into the memory (gui/resources.py)
    "telegram_on": False,  # a Telegram message when a job is done / failed (gui/telegram.py)
    "telegram_token": "",  # the user's bot (only on this computer; never in diagnostics)
    "telegram_chat": "",
    "telegram_bot": "",
    "telegram_done": True,
    "telegram_failed": True,
    "telegram_photo": True,
    "remote_on": False,  # control from a phone in the home network (gui/remote.py)
    "remote_port": 8765,
    "remote_token": "",
    "remote_tailscale": False,  # also phones in the user's tailnet (Tailscale, 100.64.0.0/10)
    "remote_pin": "",  # six digits: signing in on the phone without the QR code (made when first needed)
    "user_presets": [],  # the user's own presets (gui/user_presets.py)
    "hints_off": [],  # the kinds of quality hints about the photo not to show any more (gui/image_hints.py)
    "skipped_version": "",
    "last_version": "",  # the version of the last start ("what's new" after an update)
    "last_params": None,
    "last_preset": "standard",
    "last_image": "",
    "show_advanced": False,
    "geometry": None,
    "queue": [],
}


class AppSettings:
    def __init__(self):
        self._path = paths.app_settings_file()
        self.data = dict(DEFAULTS)
        stored = paths.read_settings_file()  # falls back to the backup of a damaged file
        if stored is not None:
            if not isinstance(stored.get("settings_version"), int) and stored.get("language") == "de":
                # up to 2.0.0 German was the fixed default and got written to the file with every
                # other setting, so a stored "de" was usually never chosen → follow the system language
                stored["language"] = "auto"
            self.data.update(stored)
            self.data["settings_version"] = SETTINGS_VERSION
            if "tour_done" not in stored:  # used before the guide existed: only on request (About)
                self.data["tour_done"] = True
            self._backup()

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def _backup(self) -> None:
        """The settings that loaded fine, as settings.json.bak (used if settings.json gets damaged)."""
        try:
            self._path.with_name(self._path.name + ".bak").write_text(json.dumps(self.data, indent=2),
                                                                       encoding="utf-8")
        except OSError:
            pass

    def save(self) -> None:
        """Write to a temporary file and replace settings.json with it: an interrupted write (crash,
        power loss) never leaves a half-written file, which would reset all settings and the queue."""
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            return
        for attempt in range(5):
            try:
                os.replace(tmp, self._path)
                return
            except PermissionError:  # Windows: the file is open in another program for a moment
                time.sleep(0.05 * (attempt + 1))
            except OSError:
                break
        try:
            tmp.unlink()
        except OSError:
            pass


_instance: AppSettings | None = None


def app_settings() -> AppSettings:
    global _instance
    if _instance is None:
        _instance = AppSettings()
    return _instance
