"""A stand-in for ``python -m clipasso_studio.headless`` in the tests of StudioCore's EngineClient: the same JSON lines,
with ways to misbehave.

    python3 fake_engine.py MODE [N]

MODE: echo · crash_after N (ends with exit code 3 after N answers) · garbage (a line that is not JSON first) · slow
(answers after 2 s) · stderr_secret (writes a secret to stderr) · protocol2 (speaks another protocol). Every mode
answers ``hello``, ``events`` (sends N events, then answers), ``huge`` (an 8 MB answer) and ``shutdown``.
"""

import json
import sys
import time

mode = sys.argv[1] if len(sys.argv) > 1 else "echo"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
out = sys.stdout.buffer


def send(obj):
    out.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
    out.flush()


if mode == "garbage":
    out.write(b"this is not json\n")
    out.flush()
if mode == "stderr_secret":
    sys.stderr.write("a normal log line\nremote_token=SECRET123 should never be kept\n")
    sys.stderr.flush()

answered = 0
for raw in sys.stdin.buffer:
    req = json.loads(raw)
    op, rid, args = req["op"], req["id"], req.get("args", {})
    if mode == "crash_after" and answered >= limit:
        sys.exit(3)
    if mode == "slow":
        time.sleep(2)
    if op == "hello":
        send({"id": rid, "ok": True, "result": {"protocol": 2 if mode == "protocol2" else 1, "app_version": "fake"}})
    elif op == "events":
        for i in range(int(args.get("n", 3))):
            send({"event": "iteration", "job": "j1", "data": {"seed": 0, "it": i, "total": 100}})
        send({"id": rid, "ok": True, "result": {"sent": args.get("n", 3)}})
    elif op == "huge":
        send({"id": rid, "ok": True, "result": {"blob": "x" * (8 * 1024 * 1024)}})
    elif op == "fail":
        send({"id": rid, "ok": False, "error": {"code": "busy", "message": "a job is already running"}})
    elif op == "shutdown":
        send({"id": rid, "ok": True, "result": {}})
        sys.exit(0)
    else:
        send({"id": rid, "ok": True, "result": {"op": op, "args": args}})
    answered += 1
