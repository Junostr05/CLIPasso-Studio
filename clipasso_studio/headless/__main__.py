"""``python -m clipasso_studio.headless [--export-schema PATH] [--export-models PATH]``"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clipasso_studio.headless",
                                     description="CLIPasso Studio's sketch engine for the Mac app")
    parser.add_argument("--export-schema", metavar="PATH", help="write the parameter schema as JSON and end")
    parser.add_argument("--export-models", metavar="PATH", help="write the model list as JSON and end")
    args = parser.parse_args(argv)
    if args.export_schema or args.export_models:
        from . import export

        if args.export_schema:
            export.write_json(args.export_schema, export.export_schema())
        if args.export_models:
            export.write_json(args.export_models, export.export_models())
        return 0
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
