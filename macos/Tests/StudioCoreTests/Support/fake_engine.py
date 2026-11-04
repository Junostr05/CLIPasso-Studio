"""A stand-in for ``python -m clipasso_studio.headless`` in the tests of StudioCore's EngineClient: the same JSON lines,
with ways to misbehave.

    python3 fake_engine.py MODE [N]

MODE: echo · crash_after N (ends with exit code 3 after N answers) · garbage (a line that is not JSON first) · slow
(answers after 2 s) · stderr_secret (writes a secret to stderr) · protocol2 (speaks another protocol) · job DIR
(``start`` "computes" by copying the finished job folder DIR into output_root) · job_fails (``start`` ends with
job_failed) · needs KEYS DIR (``required_models`` lists the comma-separated KEYS as missing until ``convert_model``
found each downloaded in dest_root's partial folder; ``start`` as in job DIR). Every mode answers ``hello``, ``events`` (sends N events, then answers), ``huge`` (an 8 MB answer) and
``shutdown``.
"""

import json
import os
import shutil
import sys
import time

mode = sys.argv[1] if len(sys.argv) > 1 else "echo"
limit = int(sys.argv[2]) if len(sys.argv) > 2 and mode in ("crash_after", "events") else 0
source = sys.argv[2] if mode == "job" else sys.argv[3] if mode == "needs" else ""
needed = sys.argv[2].split(",") if mode == "needs" else []
converted = set()
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
    elif op == "required_models":
        send({"id": rid, "ok": True, "result": {"required": needed, "missing": [k for k in needed if k not in converted]}})
    elif op == "convert_model" and mode == "needs":
        part = os.path.join(args["dest_root"], ".partial", args["key"] + ".part")
        if os.path.isfile(part):
            converted.add(args["key"])
            send({"id": rid, "ok": True, "result": {"path": os.path.join(args["dest_root"], args["key"])}})
        else:
            send({"id": rid, "ok": False, "error": {"code": "not_downloaded", "message": f"no {part}"}})
    elif op == "start" and mode in ("job", "job_fails", "needs"):
        job_dir = os.path.join(args["output_root"], os.path.basename(source) if source else "failed-job")
        send({"id": rid, "ok": True, "result": {"job": "j1", "job_dir": job_dir}})
        total = int(args["settings"].get("num_iter", 5))
        for i in range(total):
            send({"event": "iteration", "job": "j1", "data": {"seed": 1000, "it": i, "total": total}})
        if mode in ("job", "needs"):
            shutil.copytree(source, job_dir)
            send({"event": "job_done", "job": "j1", "data": {"job_dir": job_dir}})
        else:
            send({"event": "job_failed", "job": "j1", "data": {"message": "RuntimeError: made up", "job_dir": job_dir}})
    elif op == "shutdown":
        send({"id": rid, "ok": True, "result": {}})
        sys.exit(0)
    else:
        send({"id": rid, "ok": True, "result": {"op": op, "args": args}})
    answered += 1
