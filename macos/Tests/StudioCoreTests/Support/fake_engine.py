"""A stand-in for ``python -m clipasso_studio.headless`` in the tests of StudioCore's EngineClient: the same JSON lines,
with ways to misbehave.

    python3 fake_engine.py MODE [N]

MODE: echo · crash_after N (ends with exit code 3 after N answers) · garbage (a line that is not JSON first) · slow
(answers after 2 s) · stderr_secret (writes a secret to stderr) · protocol2 (speaks another protocol) · job DIR
(``start`` "computes" by copying the finished job folder DIR into output_root, sending input and attention
pictures first) · job_fails (``start`` ends with
job_failed) · needs KEYS DIR (``required_models`` lists the comma-separated KEYS as missing until ``convert_model``
found each downloaded in dest_root's partial folder – then moved to KEY/KEY.pt; ``model_roles`` has them for the
mask's role; ``start`` as in job DIR) · mask
PNG (``mask`` with compute answers "computing", then sends "mask_ready"; asked again it gives PNG as the model's
probability; ``save_mask`` keeps a copy of the mask given – then ``mask`` gives it as the user's – and
``remove_mask`` removes it; ``detail`` gives the map ``save_detail`` kept – a copy, at 32 × 24 –, ``portrait`` first
answers missing_model, then finds a "face": the left half more).
Every mode answers ``hello``, ``events`` (sends N events, then answers), ``huge`` (an 8 MB answer) and
``shutdown``.
"""

import base64
import json
import os
import shutil
import sys
import struct
import tempfile
import time
import zlib

mode = sys.argv[1] if len(sys.argv) > 1 else "echo"
limit = int(sys.argv[2]) if len(sys.argv) > 2 and mode in ("crash_after", "events") else 0
source = sys.argv[2] if mode in ("job", "mask") else sys.argv[3] if mode == "needs" else ""
needed = sys.argv[2].split(",") if mode == "needs" else []
converted = set()
kept = tempfile.mkdtemp(prefix="fake-engine-")
edited = os.path.join(kept, "edited.png")
detail = os.path.join(kept, "detail.png")
portraits = 0


def grey_png(path, width, height, value):
    """An 8-bit grey PNG; ``value(x, y)`` its bytes."""
    raw = b"".join(b"\0" + bytes(value(x, y) for x in range(width)) for y in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def temp_copy(path):
    fd, copy = tempfile.mkstemp(suffix=".png", dir=kept)
    os.close(fd)
    shutil.copyfile(path, copy)
    return copy
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
        missing = [k for k in needed if k not in converted]
        send({"id": rid, "ok": True, "result": {"required": needed, "missing": missing}})
    elif op == "model_roles":  # (the mask's role needs the KEYS of "needs")
        missing = [k for k in needed if k not in converted]
        send({"id": rid, "ok": True, "result": {
            "roles": [{"category": "mask", "key": "mask_model", "value": args["settings"].get("mask_model", "birefnet"),
                       "enabled": True, "models": needed, "missing": missing, "experimental": False,
                       "choices": [{"value": "birefnet", "experimental": False},
                                   {"value": "u2net", "experimental": True}]}],
            "in_use": needed, "missing": missing,
            "methods": {m: bool(missing) and m == args["method"] for m in args.get("methods", {})}}})
    elif op == "convert_model" and mode == "needs":
        part = os.path.join(args["dest_root"], ".partial", args["key"] + ".part")
        if os.path.isfile(part):  # (as model_store.convert_downloaded: the model in place, the download gone)
            converted.add(args["key"])
            model = os.path.join(args["dest_root"], args["key"], args["key"] + ".pt")
            os.makedirs(os.path.dirname(model), exist_ok=True)
            shutil.move(part, model)
            send({"id": rid, "ok": True, "result": {"path": model}})
        else:
            send({"id": rid, "ok": False, "error": {"code": "not_downloaded", "message": f"no {part}"}})
    elif op == "start" and mode in ("job", "job_fails", "needs"):
        job_dir = os.path.join(args["output_root"], os.path.basename(source) if source else "failed-job")
        send({"id": rid, "ok": True, "result": {"job": "j1", "job_dir": job_dir}})
        total = int(args["settings"].get("num_iter", 5))
        grey_png(os.path.join(kept, "view.png"), 4, 3, lambda x, y: 200)  # (the views the pipeline sends)
        with open(os.path.join(kept, "view.png"), "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        send({"event": "input", "job": "j1", "data": {"seed": 1000, "png_b64": b64, "mask_png_b64": b64}})
        send({"event": "attention", "job": "j1", "data": {"seed": 1000, "png_b64": b64}})
        for i in range(total):
            send({"event": "iteration", "job": "j1", "data": {"seed": 1000, "it": i, "total": total}})
        if mode in ("job", "needs"):
            shutil.copytree(source, job_dir)
            send({"event": "job_done", "job": "j1", "data": {"job_dir": job_dir}})
        else:
            send({"event": "job_failed", "job": "j1", "data": {"message": "RuntimeError: made up", "job_dir": job_dir}})
    elif op == "mask" and mode == "mask":
        computing = bool(args.get("compute"))
        mine = edited if os.path.isfile(edited) else None
        send({"id": rid, "ok": True, "result": {"probability": None if computing else source, "edited": mine,
                                                "width": 32, "height": 24, "threshold": 0.5, "computing": computing}})
        if computing:
            send({"event": "mask_ready", "job": None, "data": {"image": args["image"], "model": args["model"],
                                                               "probability": source}})
    elif op == "save_mask" and mode == "mask":
        shutil.copyfile(args["mask"], edited)
        send({"id": rid, "ok": True, "result": {"path": edited}})
    elif op == "remove_mask" and mode == "mask":
        if os.path.isfile(edited):
            os.remove(edited)
        send({"id": rid, "ok": True, "result": {}})
    elif op == "detail" and mode == "mask":
        has = os.path.isfile(detail)
        send({"id": rid, "ok": True, "result": {"map": temp_copy(detail) if has else None, "width": 32, "height": 24,
                                                "has": has, "normal": 128}})
    elif op == "save_detail" and mode == "mask":
        shutil.copyfile(args["map"], detail)
        send({"id": rid, "ok": True, "result": {"path": detail}})
    elif op == "portrait" and mode == "mask":
        portraits += 1
        if portraits == 1:
            send({"id": rid, "ok": False, "error": {"code": "missing_model", "message": "blazeface"}})
        else:
            send({"id": rid, "ok": True, "result": {"computing": True}})
            faces = os.path.join(kept, f"faces{portraits}.png")
            grey_png(faces, 32, 24, lambda x, y: 200 if x < 16 else 128)
            send({"event": "portrait_ready", "job": None, "data": {"image": args["image"], "model": "blazeface",
                                                                   "map": faces}})
    elif op == "shutdown":
        send({"id": rid, "ok": True, "result": {}})
        sys.exit(0)
    else:
        send({"id": rid, "ok": True, "result": {"op": op, "args": args}})
    answered += 1
