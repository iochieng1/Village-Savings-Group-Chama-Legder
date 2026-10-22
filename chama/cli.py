"""Command line: ``python -m chama <command>``.

export  write a group's ledger to JSON
verify  check an exported ledger, optionally against a fingerprint from your SMS
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import db, money
from .export import InvalidExport, export_group, verify_export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chama", description="Chama Ledger tools")
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("export", help="export a group's ledger as JSON")
    exp.add_argument("--database", default=os.getenv("CHAMA_DATABASE", "chama.db"))
    exp.add_argument("--group", type=int, required=True)
    exp.add_argument("--output", "-o", help="file to write (default: stdout)")

    ver = sub.add_parser("verify", help="verify an exported ledger without the server")
    ver.add_argument("file")
    ver.add_argument("--fingerprint", help="fingerprint from your meeting SMS, e.g. 1A2B-3C4D")
    ver.add_argument("--at", type=int, help="entry number given in the same SMS")

    args = parser.parse_args(argv)

    if args.command == "export":
        data = json.dumps(export_group(db.connect(args.database), args.group), indent=2, ensure_ascii=False)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(data + "\n")
        else:
            print(data)
        return 0

    if bool(args.fingerprint) != (args.at is not None):
        parser.error("--fingerprint and --at go together")
    try:
        with open(args.file, encoding="utf-8") as fh:
            report = verify_export(json.load(fh), args.fingerprint, args.at)
    except (OSError, ValueError, InvalidExport) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if report["ok"]:
        print(f"OK: {report['entries_checked']} entries verified, head #{report['head_seq']} {report['head_fingerprint']}")
        print(f"   {report['checkpoints_matched']} meeting fingerprint(s) match")
        if "sms_check" in report:
            print(f"   your SMS fingerprint {report['sms_check']['expected']} at #{report['sms_check']['seq']} matches")
        s = report["summary"]
        print(f"   savings {money.fmt(s['total_savings'])}, cash {money.fmt(s['cash_expected'])}, "
              f"loans outstanding {money.fmt(s['loans_outstanding'])}")
        return 0
    if report.get("broken_at") is not None:
        print(f"TAMPERED: entry #{report['broken_at']}: {report['reason']}")
    if "sms_check" in report and not report["sms_check"]["ok"]:
        check = report["sms_check"]
        print(f"MISMATCH: your SMS says {check['expected']} at #{check['seq']}, the ledger has {check['found']}")
    return 1
