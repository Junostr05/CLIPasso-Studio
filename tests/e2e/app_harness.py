"""The app for the browser tests of the phone page: offscreen, with folders of its own and one finished result,
the remote switched on at a free port. Prints the address (with the access code) and the PIN; quits when its
standard input closes. Optional: a port (the same one again after a "restart"), and CLIPASSO_E2E_VERSION – the app
then says it is that version (an update from the phone, faked)."""

import os
import socket
import sys
import threading


def main():
    data, out, lang = sys.argv[1:4]
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["XDG_DATA_HOME"] = data
    os.environ["LOCALAPPDATA"] = data
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    import clipasso_studio

    if os.environ.get("CLIPASSO_E2E_VERSION"):  # (before the app's modules take the version)
        clipasso_studio.__version__ = os.environ["CLIPASSO_E2E_VERSION"]
    from clipasso_studio.gui import theme
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.i18n import i18n

    theme.load_fonts()
    theme.apply(app, "dark")
    i18n.set_language(lang)
    if not port:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    app_settings().data.update(output_dir=out, remote_on=True, remote_port=port, tour_done=True,
                               last_version=clipasso_studio.__version__, check_updates=False)
    from tests.helpers import fake_job, fake_scene_job

    os.makedirs(out, exist_ok=True)
    if not os.path.isdir(os.path.join(out, "camel_e2e")):  # (started again: the results are there)
        fake_job(out, "camel_e2e", os.path.join(data, "camel_e2e.png"), 31.0)
        fake_scene_job(out, "scene_e2e", os.path.join(data, "scene_e2e.png"))
    from clipasso_studio.gui import dialogs, remote
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.controller.start_next = lambda: None  # (the tests queue jobs, they never compute one)
    w.resize(1280, 860)
    w.show()
    print("URL", f"http://127.0.0.1:{port}/?t={remote.token()}", flush=True)
    print("PIN", remote.pin(), flush=True)

    class _Quit(QObject):
        now = Signal()

    quit_ = _Quit()
    quit_.now.connect(app.quit)  # (queued: emitted in the thread below)
    threading.Thread(target=lambda: (sys.stdin.read(), quit_.now.emit()), daemon=True).start()
    app.exec()
    dialogs.wait_for_threads()
    w.controller.shutdown()
    w.phone.shutdown()


if __name__ == "__main__":  # (the sketch workers start this module again: nothing may run then)
    main()
