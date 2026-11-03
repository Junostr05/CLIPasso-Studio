"""After ``swift test``: does Python read the meta.json files the Swift package wrote as the Swift side meant – and
are they byte for byte what Python itself writes for that data?

    python tools/check_swift_meta.py DIR

``DIR`` is the folder ``swift test`` was given as STUDIOCORE_EXPORT_DIR: one sub-folder per case with the
``meta.json`` Swift wrote and ``expected.json`` (what ``jobs.read_meta`` should return). Exit code 0: all read right,
1: a difference (printed), 2: nothing to check.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipasso_studio.engine import jobs  # noqa: E402


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path("")
    cases = sorted(p.parent for p in root.glob("*/expected.json")) if root.is_dir() else []
    if not cases:
        print(f"nothing to check in {root}")
        return 2
    failed = 0
    for case in cases:
        want = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        got = jobs.read_meta(str(case))
        if got != want:
            failed += 1
            for key in sorted(set(want) | set(got)):
                if want.get(key) != got.get(key):
                    print(f"{case.name}: {key}: Python reads {got.get(key)!r}, Swift meant {want.get(key)!r}")
            continue
        with tempfile.TemporaryDirectory() as tmp:  # Python writes the same data again
            shutil.copyfile(case / jobs.META_FILE, Path(tmp) / jobs.META_FILE)
            jobs.write_meta(tmp)
            python_bytes = (Path(tmp) / jobs.META_FILE).read_bytes()
        if python_bytes != (case / jobs.META_FILE).read_bytes():
            failed += 1
            print(f"{case.name}: the bytes of meta.json differ from what Python writes:\n{python_bytes.decode()}")
    print(f"{len(cases) - failed} of {len(cases)} read right")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
