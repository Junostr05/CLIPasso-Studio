"""JSON lines between the Mac app and the engine: one JSON object per line, UTF-8.

- request (stdin):  ``{"id": 12, "op": "start", "args": {…}}``
- answer (stdout):  ``{"id": 12, "ok": true, "result": {…}}``
  or ``{"id": 12, "ok": false, "error": {"code", "message"}}``
- event (stdout):   ``{"event": "iteration", "job": "j3", "data": {…}}`` – the engine's own events and fields

Bytes travel as base64 in a field named ``<field>_b64`` (``png`` → ``png_b64``), NaN and ±infinity as ``null``.
"""

from __future__ import annotations

import base64
import json
import math
import threading
import time
from typing import Any, BinaryIO, Callable

PROTOCOL_VERSION = 1


class ProtocolError(Exception):
    def __init__(self, code: str, message: str, request_id: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(item, (bytes, bytearray, memoryview)):
                out[f"{key}_b64"] = base64.b64encode(bytes(item)).decode("ascii")
            else:
                out[str(key)] = _plain(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if type(value).__module__ == "numpy":  # numpy scalars and arrays (without importing numpy here)
        return _plain(value.tolist() if hasattr(value, "shape") and value.shape else value.item())
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def encode(obj: dict) -> bytes:
    """One line of the protocol (with its new line)."""
    return json.dumps(_plain(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def decode(line: bytes) -> dict:
    """A request: ``{"id": int, "op": str, "args": dict}``; raises :class:`ProtocolError` (code ``bad_request``)."""
    try:
        data = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError("bad_request", f"not a JSON line: {exc}") from None
    if not isinstance(data, dict):
        raise ProtocolError("bad_request", "a request is a JSON object")
    rid = data.get("id")
    rid = rid if isinstance(rid, int) and not isinstance(rid, bool) else None
    if rid is None:
        raise ProtocolError("bad_request", "the request has no whole-number id")
    if not isinstance(data.get("op"), str) or not data["op"]:
        raise ProtocolError("bad_request", "the request has no op", rid)
    args = data.get("args", {})
    if not isinstance(args, dict):
        raise ProtocolError("bad_request", "args is a JSON object", rid)
    return {"id": rid, "op": data["op"], "args": args}


class Writer:
    """Writes whole lines to the protocol stream, one thread at a time."""

    def __init__(self, stream: BinaryIO):
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, obj: dict) -> None:
        line = encode(obj)
        with self._lock:
            self._stream.write(line)
            self._stream.flush()


class IterationThrottle:
    """At most ``rate`` ``iteration`` events per second and sketch (seed) of a job. The last iteration of a sketch
    (``it + 1 == total``) always goes through; one held back is sent by :meth:`flush` (before the sketch's next event)
    or by :meth:`due` once it waited long enough (when the iterations become slow)."""

    def __init__(self, rate: float = 10.0, clock: Callable[[], float] = time.monotonic):
        self.interval = 1.0 / rate
        self.clock = clock
        self._last: dict[tuple, float] = {}
        self._held: dict[tuple, dict] = {}

    def offer(self, job: str, data: dict) -> list[dict]:
        key = (job, data.get("seed"))
        now = self.clock()
        last = data.get("total") is not None and int(data.get("it", 0)) + 1 >= int(data["total"])
        if last or now - self._last.get(key, -math.inf) >= self.interval:
            self._held.pop(key, None)
            self._last[key] = now
            return [data]
        self._held[key] = data
        return []

    def flush(self, job: str, seed: Any = None) -> list[dict]:
        keys = [k for k in self._held if k[0] == job and (seed is None or k[1] == seed)]
        return [self._held.pop(k) for k in keys]

    def due(self) -> list[tuple[str, dict]]:
        now = self.clock()
        out = []
        for key in [k for k in self._held if now - self._last.get(k, -math.inf) >= self.interval]:
            self._last[key] = now
            out.append((key[0], self._held.pop(key)))
        return out
