"""Download and convert the models bundled with CLIPasso Studio.

Usage: python tools/fetch_models.py [--dest models] [--include-optional]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipasso_studio.engine import model_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=str(ROOT / "models"))
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated model keys (e.g. for the benchmark); the "
                                                   "manifest of the bundled models is left as it is")
    args = parser.parse_args()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    unknown = only - set(model_store.SPECS)
    if unknown:
        print(f"unknown model keys: {', '.join(sorted(unknown))}")
        return 2

    manifest = {}
    for key, spec in model_store.SPECS.items():
        if only and key not in only:
            continue
        if not only and not spec.bundled and not args.include_optional:
            continue
        if not only and spec.extra.get("purpose") == "benchmark":
            continue  # (the benchmark's judge: only with --only)
        target = dest / spec.filename
        if target.is_file():
            print(f"[skip] {key}: {target} exists")
        else:
            print(f"[get ] {key} ...", flush=True)
            last = [0.0]

            def progress(done, total, key=key):
                now = time.time()
                if now - last[0] > 5:
                    last[0] = now
                    pct = f"{100 * done / total:5.1f}%" if total else "preparing …"
                    print(f"       {key}: {pct}", flush=True)

            model_store.install(key, dest_root=dest, progress=progress)
        manifest[key] = {"file": spec.filename, "bytes": target.stat().st_size}
        print(f"[ ok ] {key}: {target.stat().st_size / 1e6:.1f} MB", flush=True)

    if not only:
        (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
