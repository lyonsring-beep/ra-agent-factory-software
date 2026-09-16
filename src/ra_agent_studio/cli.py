from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .application.studio import StudioService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ra-studio")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-module")
    create.add_argument("module_id")
    create.add_argument("revision_id")
    create.add_argument("name")
    create.add_argument("content")
    sub.add_parser("list-modules")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    studio = StudioService()
    if args.command == "create-module":
        result = studio.create_module_revision(
            module_id=args.module_id,
            revision_id=args.revision_id,
            name=args.name,
            content=args.content,
        )
        print(json.dumps(asdict(result), default=str, ensure_ascii=False))
        return 0
    if args.command == "list-modules":
        print(json.dumps([asdict(x) for x in studio.modules.list()], default=str, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())