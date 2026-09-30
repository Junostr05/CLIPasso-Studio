"""Model downloads continue where they stopped: dropped connections, cancel, restarts."""

import hashlib
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clipasso_studio.engine import model_store

DATA = os.urandom(3_000_000)  # three read chunks of 1 MB


class _Handler(BaseHTTPRequestHandler):
    drops = 0  # responses that are cut off halfway (connection lost)
    starts: list = []

    def do_GET(self):  # noqa: N802
        rng = self.headers.get("Range")
        start = int(rng.split("=")[1].split("-")[0]) if rng else 0
        _Handler.starts.append(start)
        if start >= len(DATA):
            self.send_response(416)
            self.end_headers()
            return
        body = DATA[start:]
        self.send_response(206 if rng else 200)
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{len(DATA) - 1}/{len(DATA)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if _Handler.drops > 0:
            _Handler.drops -= 1
            self.wfile.write(body[: len(body) // 2])
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    _Handler.drops, _Handler.starts = 0, []
    yield f"http://127.0.0.1:{httpd.server_address[1]}/model.bin"
    httpd.shutdown()


def _spec(url, sha=True):
    return model_store.ModelSpec(key="test:model", filename="test/model.pt", urls=(url,),
                                 download_sha256=hashlib.sha256(DATA).hexdigest() if sha else None,
                                 download_size=len(DATA), stored_size_mb=1, bundled=False, kind="test")


def test_a_dropped_connection_is_resumed(server, tmp_path, monkeypatch):
    monkeypatch.setattr(model_store.time, "sleep", lambda s: None)
    _Handler.drops = 1
    raw = model_store.download_raw(_spec(server), tmp_path)
    assert raw.read_bytes() == DATA
    assert _Handler.starts[0] == 0 and 0 < _Handler.starts[1] < len(DATA)  # the second request resumed


def test_a_cancelled_download_continues_next_time(server, tmp_path):
    seen = []

    def cancel():
        return len(seen) > 0  # stop after the first chunk

    with pytest.raises(InterruptedError):
        model_store.download_raw(_spec(server), tmp_path, progress=lambda d, t: seen.append(d), cancel=cancel)
    part = tmp_path / "test_model.part"
    assert 0 < part.stat().st_size < len(DATA)
    size = part.stat().st_size
    progress = []
    raw = model_store.download_raw(_spec(server), tmp_path, progress=lambda d, t: progress.append((d, t)))
    assert raw.read_bytes() == DATA
    assert _Handler.starts[-1] == size
    assert progress[0][0] > size and progress[-1] == (0, 0)  # continues counting; then "checking"


def test_a_complete_partial_file_is_not_downloaded_again(server, tmp_path):
    model_store.download_raw(_spec(server), tmp_path)
    n = len(_Handler.starts)
    assert model_store.download_raw(_spec(server), tmp_path).read_bytes() == DATA
    assert _Handler.starts[n:] in ([], [len(DATA)])  # at most a range request answered with 416


def test_a_partial_file_of_another_source_is_discarded(server, tmp_path):
    part = tmp_path / "test_model.part"
    part.write_bytes(b"x" * 1000)
    (tmp_path / "test_model.json").write_text('{"url": "http://elsewhere/model.bin"}')
    assert model_store.download_raw(_spec(server), tmp_path).read_bytes() == DATA
    assert _Handler.starts == [0]


def test_a_corrupt_download_is_removed(server, tmp_path, monkeypatch):
    spec = _spec(server)
    spec = model_store.ModelSpec(**{**spec.__dict__, "download_sha256": "0" * 64})
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        model_store.download_raw(spec, tmp_path)
    assert not (tmp_path / "test_model.part").exists()


def test_install_cleans_up_the_partial_folder(server, tmp_path, monkeypatch):
    spec = _spec(server)
    monkeypatch.setitem(model_store.SPECS, spec.key, spec)
    monkeypatch.setattr(model_store, "convert", lambda s, raw, dest: (dest.parent.mkdir(parents=True, exist_ok=True),
                                                                      dest.write_bytes(raw.read_bytes())))
    dest = model_store.install(spec.key, dest_root=tmp_path)
    assert dest.read_bytes() == DATA
    assert list(model_store.partial_dir(tmp_path).iterdir()) == []


def test_hugging_face_models_continue_after_a_cancel(server, tmp_path, monkeypatch):
    base = server.rsplit("/", 1)[0]
    monkeypatch.setattr(model_store, "_HF", base)
    files = (model_store.HFFile("unet/config.json", "unet/config.json", len(DATA)),)
    spec = model_store.ModelSpec(key="hf:test", filename="hftest/manifest.json", urls=(), download_sha256=None,
                                 download_size=len(DATA), stored_size_mb=1, bundled=False, kind="hf",
                                 extra={"repo": "some/repo", "revision": "abc", "files": files})
    monkeypatch.setitem(model_store.SPECS, spec.key, spec)
    seen = []
    with pytest.raises(InterruptedError):
        model_store.install(spec.key, dest_root=tmp_path, progress=lambda d, t: seen.append(d),
                            cancel=lambda: len(seen) > 0)
    raw = model_store.partial_dir(tmp_path) / "hf_test" / "unet" / "config.json"
    size = raw.stat().st_size
    assert 0 < size < len(DATA)
    manifest = model_store.install(spec.key, dest_root=tmp_path)
    assert _Handler.starts[-1] == size  # continued
    assert (manifest.parent / "unet" / "config.json").read_bytes() == DATA
    assert not (model_store.partial_dir(tmp_path) / "hf_test").exists()
