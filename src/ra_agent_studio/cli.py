from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os

from .application.control_contracts import CommandEnvelope
from .application.control_plane import StudioControlPlane
from .application.operation_catalog import APPLICATION_OPERATION_CATALOG
from .application.studio import StudioService


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="ra-studio")
    parser.add_argument("--token",default=os.environ.get("RA_STUDIO_TOKEN",""))
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("list-modules")
    sub.add_parser("snapshot")
    sub.add_parser("operations")
    submit=sub.add_parser("submit-command")
    submit.add_argument("operation_descriptor_id")
    submit.add_argument("exact_target_ref")
    submit.add_argument("--workspace",required=True)
    submit.add_argument("--idempotency-key",required=True)
    submit.add_argument("--expected-recovery-epoch",required=True,type=int)
    submit.add_argument("--command-id",required=True)
    submit.add_argument("--payload-json",default="{}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args=build_parser().parse_args(argv)
    studio=StudioService()
    if args.command == "list-modules":
        print(json.dumps([asdict(x) for x in studio.list_modules()],default=str,ensure_ascii=False))
        return 0
    if args.command == "snapshot":
        print(json.dumps(studio.snapshot(),ensure_ascii=False))
        return 0
    if args.command == "operations":
        print(json.dumps({
            key:{"intent":value.intent,"authority_changing":value.authority_changing}
            for key,value in APPLICATION_OPERATION_CATALOG.items()
        },ensure_ascii=False))
        return 0
    if args.command == "submit-command":
        if not args.token:
            raise SystemExit("--token or RA_STUDIO_TOKEN is required for mutation commands")
        principal=studio.authority.authenticate_bearer(args.token)
        result=StudioControlPlane(studio).execute(CommandEnvelope(
            command_id=args.command_id,
            operation_descriptor_id=args.operation_descriptor_id,
            exact_target_ref=args.exact_target_ref,
            principal_ref=principal.principal_id,
            workspace_ref=args.workspace,
            idempotency_key=args.idempotency_key,
            expected_recovery_epoch=args.expected_recovery_epoch,
            payload=json.loads(args.payload_json),
        ))
        print(json.dumps(asdict(result),default=str,ensure_ascii=False))
        return 0 if result.standing in {"COMMITTED","REPLAYED"} else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
