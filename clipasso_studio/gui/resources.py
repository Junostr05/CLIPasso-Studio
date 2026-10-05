"""Resource guard: will a job fit into this computer's memory? Checked before it is started or queued, so a
job that cannot fit is changed (or knowingly started) instead of failing after minutes.

The need per method comes from measurements: the peak memory of a sketch process on the CPU with
``tools/benchmark.py`` (rounded up), the graphics memory from the sizes of the networks plus their
activations. Without PyTorch (the app checks this before any worker runs)."""

from __future__ import annotations

from dataclasses import dataclass

from .. import settings_schema as schema

GB = 1e9
SETTING = "resource_check"  # app setting: ask before a job that does not fit (False: "don't ask again")

# peak memory of one sketch process computing on the CPU
CPU_RAM = {"clipasso": 3.0 * GB, "swiftsketch": 2.5 * GB, "controlsketch": 9.0 * GB, "scenesketch": 2.5 * GB}
# with a graphics card: the process itself (the networks pass through it while loading) and the graphics memory
GPU_RAM = {"clipasso": 2.0 * GB, "swiftsketch": 2.0 * GB, "controlsketch": 5.0 * GB, "scenesketch": 3.0 * GB}
VRAM = {"clipasso": 2.5 * GB, "swiftsketch": 1.5 * GB, "controlsketch": 4.0 * GB, "scenesketch": 3.0 * GB}
FP32_VRAM = {"controlsketch": 2.0, "swiftsketch": 1.0}  # factor with "Always compute in fp32"
SDXL_CPU_RAM = 15 * GB  # ControlSketch's SDXL attention on the CPU (small graphics card or the CPU edition)
SDXL_OFFLOAD_RAM = 9 * GB  # … piece by piece through a small graphics card: its float16 weights wait in the RAM
SDXL_OFFLOAD_VRAM = 2.5 * GB
VRAM_USABLE = 0.9  # the desktop and the driver keep some of the graphics memory
RAM_RESERVE = 1.5 * GB  # the app and the system


@dataclass
class Need:
    ram: float  # bytes this job needs at most
    vram: float
    ram_free: float  # bytes available now (0: not known)
    vram_free: float
    workers: int = 1

    @property
    def short(self) -> list[str]:
        """What is short: "ram" and / or "vram"."""
        out = []
        if self.ram_free and self.ram > self.ram_free:
            out.append("ram")
        if self.vram_free and self.vram > self.vram_free:
            out.append("vram")
        return out


def _memory() -> tuple[float, float]:
    """(available RAM, total RAM) in bytes; (0, 0) when unknown."""
    try:
        import psutil

        vm = psutil.virtual_memory()
        return float(vm.available), float(vm.total)
    except Exception:
        return 0.0, 0.0


def need(settings: dict, card: dict | None = None, gpu_precision: str = "auto",
         memory: tuple[float, float] | None = None, cores: int | None = None) -> Need:
    """The memory a job with these settings needs on this computer (``card``: the graphics card it computes on,
    None: the CPU)."""
    from ..engine import runner
    from ..engine.methods.requirements import controlsketch_uses_sdxl, sdxl_on_cpu
    from .app_settings import app_settings

    s = schema.normalize(settings)
    method = schema.method_of(s)
    available, _total = memory if memory is not None else _memory()
    if card is None:
        hw = (cores or runner.hardware_info()[0], int(available))
        workers = runner.plan_workers(s, len(_seeds(s)), auto=app_settings().get("parallel_sketches", "auto") == "auto",
                                      cuda=False, hw=hw)
        ram, vram = CPU_RAM[method] * workers, 0.0
    else:
        workers = 1
        ram = GPU_RAM[method]
        vram = VRAM[method] * (FP32_VRAM.get(method, 1.0) if gpu_precision == "fp32" else 1.0)
    if method == "controlsketch" and controlsketch_uses_sdxl(s):  # (one step after the other: the larger counts)
        if card is None or sdxl_on_cpu(float(card.get("memory_gb") or 0)) and s.get("sdxl_place") == "cpu":
            ram = max(ram, SDXL_CPU_RAM)
        elif sdxl_on_cpu(float(card.get("memory_gb") or 0)):
            ram, vram = max(ram, SDXL_OFFLOAD_RAM), max(vram, SDXL_OFFLOAD_VRAM)
    vram_free = float(card.get("memory_gb") or 0) * 2 ** 30 * VRAM_USABLE if card else 0.0
    return Need(ram=ram, vram=vram, ram_free=max(0.0, available - RAM_RESERVE) if available else 0.0,
                vram_free=vram_free, workers=workers)


def _seeds(s: dict) -> list:
    from ..engine import jobs

    return jobs.job_seeds(s)


def suggestion(settings: dict, n: Need) -> dict | None:
    """Changes to the settings that need less memory; None when there are none."""
    from .controller import smaller_settings

    s = schema.normalize(settings)
    out = {}
    if "ram" in n.short and s.get("multiprocess"):  # (the automatic parallel sketches already fit the memory)
        out["multiprocess"] = False
    if "vram" in n.short or "ram" in n.short:
        out.update(smaller_settings(s) or {})
    if "vram" in n.short and not out:
        out["device"] = "cpu"
    return {k: v for k, v in out.items() if s.get(k) != v} or None


def describe(changes: dict) -> str:
    """The suggested changes in words: "Render size: 384, Turbo: on"."""
    from .i18n import i18n, tr

    parts = []
    for key, value in changes.items():
        name = tr(f"param.{key}.label") if i18n.has(f"param.{key}.label") else key
        if isinstance(value, bool):
            value = tr("ui.resources.on" if value else "ui.resources.off")
        elif key == "device":
            value = tr("ui.resources.cpu")
        parts.append(f"{name}: {value}")
    return ", ".join(parts)


def shortage(settings: dict) -> tuple[str, dict | None] | None:
    """Without asking (the phone): (what is short, in words; the smaller settings or None) – None when the memory
    is enough, the check is switched off or the hardware is not known yet."""
    from .app_settings import app_settings
    from .hardware import cached, job_gpu
    from .i18n import tr

    if not app_settings().get(SETTING, True):
        return None
    if schema.normalize(settings).get("device") != "cpu" and cached() is None:
        return None
    n = need(settings, job_gpu(settings), app_settings().get("gpu_precision", "auto"))
    if not n.short:
        return None
    lines = []
    if "ram" in n.short:
        lines.append(tr("ui.resources.ram", need=f"{n.ram / GB:.0f}", free=f"{n.ram_free / GB:.0f}"))
    if "vram" in n.short:
        lines.append(tr("ui.resources.vram", need=f"{n.vram / GB:.0f}", free=f"{n.vram_free / GB:.0f}"))
    return " ".join(lines), suggestion(settings, n)


def confirm(parent, settings: dict) -> dict | None:
    """Before a job is started or queued: the settings to use (perhaps smaller ones the user accepted), or None
    when the user cancels. Asks only when memory is short."""
    from PySide6.QtWidgets import QCheckBox, QMessageBox

    from .. import APP_NAME
    from .app_settings import app_settings
    from .hardware import cached, job_gpu
    from .i18n import tr

    if not app_settings().get(SETTING, True):
        return settings
    if schema.normalize(settings).get("device") != "cpu" and cached() is None:
        return settings  # the hardware probe has not answered yet: GPU or not is unknown
    n = need(settings, job_gpu(settings), app_settings().get("gpu_precision", "auto"))
    short = n.short
    if not short:
        return settings
    changes = suggestion(settings, n)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(APP_NAME)
    box.setText(tr("ui.resources.title"))
    lines = []
    if "ram" in short:
        lines.append(tr("ui.resources.ram", need=f"{n.ram / GB:.0f}", free=f"{n.ram_free / GB:.0f}"))
    if "vram" in short:
        lines.append(tr("ui.resources.vram", need=f"{n.vram / GB:.0f}", free=f"{n.vram_free / GB:.0f}"))
    lines.append(tr("ui.resources.smaller", changes=describe(changes)) if changes else tr("ui.resources.no_smaller"))
    box.setInformativeText("\n".join(lines))
    smaller = box.addButton(tr("ui.resources.use_smaller"), QMessageBox.AcceptRole) if changes else None
    anyway = box.addButton(tr("ui.resources.anyway"), QMessageBox.DestructiveRole)
    box.addButton(tr("ui.cancel"), QMessageBox.RejectRole)
    never = QCheckBox(tr("ui.resources.dont_ask"))
    box.setCheckBox(never)
    box.exec()
    clicked = box.clickedButton()
    if never.isChecked() and clicked is not None and clicked in (smaller, anyway):
        app_settings().set(SETTING, False)
    if smaller is not None and clicked is smaller:
        return {**settings, **changes}
    if clicked is anyway:
        return settings
    return None
