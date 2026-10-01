"""The app starts without PyTorch (about 3 s): only the workers and the hardware probe load it."""

import json
import subprocess
import sys


def test_main_window_does_not_import_torch(tmp_path):
    code = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from clipasso_studio.gui.main_window import MainWindow\n"
        "w = MainWindow(); w.show()\n"
        "for _ in range(10): app.processEvents()\n"
        "w.studio.params.set_method('controlsketch'); w.studio._update_estimate(); w.show_page('models')\n"
        "w.show_page('settings'); w.show_page('gallery'); w.show_page('queue')\n"
        "for _ in range(10): app.processEvents()\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('torch', 'torchvision', 'diffusers')))\n"
        "w.controller.shutdown(); w.close()\n"
    )
    env = {**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(tmp_path),
           "LOCALAPPDATA": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "[]", out.stdout


def test_hardware_probe_runs_in_a_child_process(user_data):
    from clipasso_studio.gui import hardware

    info = hardware.store(hardware.probe())
    assert "torch" in info and isinstance(info["gpus"], list) and "cuda" in info
    assert hardware.cached() == info
    assert hardware.has_cuda() == bool(info["cuda"])
    bad = hardware.store(json.dumps({"error": "no torch"}))
    assert "error" in bad and hardware.cached() == info  # a failed probe is not kept
