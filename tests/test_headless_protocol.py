"""The JSON-lines protocol between the Mac app and the engine (clipasso_studio/headless/protocol.py)."""

from __future__ import annotations

import io
import json
import math
import threading

import numpy as np
import pytest

from clipasso_studio.headless import protocol
from clipasso_studio.headless.protocol import IterationThrottle, ProtocolError, Writer, decode, encode


def test_one_object_per_line():
    line = encode({"id": 1, "ok": True})
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    assert json.loads(line) == {"id": 1, "ok": True}
    assert protocol.PROTOCOL_VERSION == 1


def test_bytes_become_base64_fields():
    data = json.loads(encode({"event": "input", "data": {"png": b"\x89PNG", "mask_png": b"", "seed": 0}}))
    assert data["data"] == {"png_b64": "iVBORw==", "mask_png_b64": "", "seed": 0}


def test_non_finite_numbers_are_null():
    data = json.loads(encode({"eta": float("nan"), "a": [math.inf, -math.inf, 1.5], "t": (1, 2)}))
    assert data == {"eta": None, "a": [None, None, 1.5], "t": [1, 2]}


def test_numpy_values_are_plain():
    data = json.loads(encode({"f": np.float32(0.5), "i": np.int64(3), "b": np.bool_(True), "n": np.float64("nan")}))
    assert data == {"f": 0.5, "i": 3, "b": True, "n": None}


def test_umlauts_stay_readable():
    line = encode({"path": "Ausgabe ö/Bild Ä.png"})
    assert "Bild Ä".encode("utf-8") in line


def test_large_payload_is_one_line():
    svg = "<svg>" + "M 1 2 C 3 4 5 6 7 8\n" * 250_000 + "</svg>"  # ~5 MB, with new lines in the text
    line = encode({"event": "preview", "data": {"svg": svg, "png": b"\0" * 1_000_000}})
    assert len(line) > 5_000_000 and line.count(b"\n") == 1 and line.endswith(b"\n")
    assert json.loads(line)["data"]["svg"] == svg


@pytest.mark.parametrize("line", [b"not json\n", b"[1, 2]\n", b'{"id": 1}\n', b'{"id": "1", "op": "hello"}\n',
                                  b'{"id": 1, "op": 5}\n', b'{"id": 1, "op": "start", "args": []}\n', b"\xff\n"])
def test_decode_rejects(line):
    with pytest.raises(ProtocolError) as err:
        decode(line)
    assert err.value.code == "bad_request" and err.value.message


def test_decode_accepts():
    assert decode(b'{"id": 3, "op": "hello"}\n') == {"id": 3, "op": "hello", "args": {}}
    assert decode(b'{"id": 4, "op": "start", "args": {"target": "a.png"}}') == {
        "id": 4, "op": "start", "args": {"target": "a.png"}}


def test_decode_keeps_the_id_of_a_bad_request():
    with pytest.raises(ProtocolError) as err:
        decode(b'{"id": 7, "op": 5}')
    assert err.value.request_id == 7


def test_writer_is_thread_safe():
    out = io.BytesIO()
    w = Writer(out)
    big = "x" * 20_000

    def send(n):
        for i in range(200):
            w.send({"n": n, "i": i, "pad": big})

    threads = [threading.Thread(target=send, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = out.getvalue().split(b"\n")[:-1]
    assert len(lines) == 800 and all(json.loads(line)["pad"] == big for line in lines)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _it(seed, it, total=1000):
    return {"seed": seed, "it": it, "total": total}


def test_throttle_limits_and_keeps_the_last():
    clock = _Clock()
    th = IterationThrottle(rate=10.0, clock=clock)
    sent = []
    for i in range(100):  # 100 iterations within one second
        clock.now = i / 100
        sent += th.offer("j1", _it(0, i, total=100))
    assert 9 <= len(sent) <= 11
    assert sent[-1]["it"] == 99  # it + 1 == total always goes through
    assert th.flush("j1") == []


def test_throttle_per_seed():
    clock = _Clock()
    th = IterationThrottle(rate=10.0, clock=clock)
    assert th.offer("j1", _it(0, 0)) == [_it(0, 0)]
    assert th.offer("j1", _it(1000, 0)) == [_it(1000, 0)]  # another sketch of the job: its own budget
    assert th.offer("j1", _it(0, 1)) == []


def test_throttle_flush_gives_the_held_back_one():
    clock = _Clock()
    th = IterationThrottle(rate=10.0, clock=clock)
    th.offer("j1", _it(0, 0))
    clock.now = 0.01
    assert th.offer("j1", _it(0, 1)) == []
    clock.now = 0.02
    assert th.offer("j1", _it(0, 2)) == []
    assert th.flush("j1", seed=0) == [_it(0, 2)]
    assert th.flush("j1", seed=0) == []


def test_throttle_due_sends_what_waited_long_enough():
    clock = _Clock()
    th = IterationThrottle(rate=10.0, clock=clock)
    th.offer("j1", _it(0, 0))
    clock.now = 0.01
    th.offer("j1", _it(0, 1))
    assert th.due() == []
    clock.now = 0.2  # no new iteration came – the held back one is not kept back for ever
    assert th.due() == [("j1", _it(0, 1))]
    assert th.due() == []
