"""Export the ledger and verify an exported copy independently.

The export contains everything needed to recompute balances and check the hash
chain, but never PINs, and phone numbers are masked. Checkpoints inside an
export could be forged along with the entries, so the independent anchor is the
fingerprint a member received by SMS: ``verify_export(..., fingerprint=, at_seq=)``
checks the export against it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import date

from . import db
from .dates import utc_now
from .ledger import Checkpoint, Entry, Verification, fingerprint, verify
from .phone import mask
from .service import get_group, list_members
from .state import project
from .statements import group_summary

FORMAT = "chama-ledger/1"


def export_group(conn: sqlite3.Connection, group_id: int) -> dict:
    group = get_group(conn, group_id)
    entries = db.load_entries(conn, group_id)
    checkpoints = db.load_checkpoints(conn, group_id)
    head = entries[-1] if entries else None
    return {
        "format": FORMAT,
        "exported_at": utc_now().isoformat(),
        "group": asdict(group),
        "members": [
            {"id": m.id, "name": m.name, "role": m.role, "phone": mask(m.phone), "active": m.active}
            for m in list_members(conn, group_id)
        ],
        "entries": [asdict(e) for e in entries],
        "checkpoints": [asdict(c) for c in checkpoints],
        "head": {"seq": head.seq if head else 0, "fingerprint": fingerprint(head.hash) if head else None},
    }


class InvalidExport(ValueError):
    pass


def verify_export(
    data: dict,
    fingerprint_from_sms: str | None = None,
    at_seq: int | None = None,
    today: date | None = None,
) -> dict:
    if data.get("format") != FORMAT:
        raise InvalidExport(f"not a {FORMAT} export")
    try:
        entries = [Entry(**e) for e in data["entries"]]
        checkpoints = [Checkpoint(**c) for c in data["checkpoints"]]
    except (KeyError, TypeError) as exc:
        raise InvalidExport(f"malformed export: {exc}") from exc

    result: Verification = verify(entries, checkpoints)
    report = {
        "ok": result.ok,
        "entries_checked": result.entries_checked,
        "head_seq": result.head_seq,
        "head_fingerprint": result.fingerprint,
        "checkpoints_matched": result.checkpoints_matched,
        "broken_at": result.broken_at,
        "reason": result.reason,
    }

    if fingerprint_from_sms:
        wanted = fingerprint_from_sms.strip().upper()
        entry = next((e for e in entries if e.seq == at_seq), None)
        actual = fingerprint(entry.hash) if entry else None
        report["sms_check"] = {"seq": at_seq, "expected": wanted, "found": actual, "ok": actual == wanted}
        report["ok"] = report["ok"] and actual == wanted

    if result.ok:
        report["summary"] = asdict(group_summary(project(entries), today or date.today()))
    return report
