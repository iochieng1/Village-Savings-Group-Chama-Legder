"""Meeting close: checkpoint the ledger, count the cash and tell every member.

The SMS each member receives carries the ledger fingerprint at that moment.
Because members hold those messages on their own phones, nobody (not even
whoever runs the server) can rewrite past records without the mismatch
showing up when the ledger is verified.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from . import db, money
from .dates import utc_now
from .i18n import t
from .ledger import GENESIS_HASH, Verification, fingerprint, verify
from .service import ChamaError, Member, require_official, get_group, list_members
from .sms import SmsGateway
from .state import project
from .statements import member_statement


@dataclass
class MeetingResult:
    seq: int
    hash: str
    fingerprint: str
    expected_cash: int
    counted_cash: int | None
    sms_sent: int

    @property
    def cash_difference(self) -> int | None:
        return None if self.counted_cash is None else self.counted_cash - self.expected_cash


def verify_group(conn: sqlite3.Connection, group_id: int) -> Verification:
    return verify(db.load_entries(conn, group_id), db.load_checkpoints(conn, group_id))


def _cash_line(expected: int, counted: int | None, lang: str) -> str:
    if counted is None:
        return ""
    difference = counted - expected
    if difference == 0:
        return t("cash.balanced", lang)
    key = "cash.over" if difference > 0 else "cash.short"
    return t(key, lang, amount=money.fmt(abs(difference)))


def close_meeting(
    conn: sqlite3.Connection,
    group_id: int,
    by: Member,
    gateway: SmsGateway,
    counted_cash: int | None = None,
    note: str = "",
    now: datetime | None = None,
) -> MeetingResult:
    require_official(by, group_id)
    if counted_cash is not None and counted_cash < 0:
        raise ChamaError("counted cash cannot be negative")
    check = verify_group(conn, group_id)
    if not check.ok:
        raise ChamaError(f"ledger failed verification at entry #{check.broken_at}: {check.reason}")

    now = now or utc_now()
    entries = db.load_entries(conn, group_id)
    head_seq = entries[-1].seq if entries else 0
    head_hash = entries[-1].hash if entries else GENESIS_HASH
    expected = project(entries).cash
    conn.execute(
        "INSERT INTO checkpoints (group_id, seq, hash, closed_at, closed_by, expected_cash, counted_cash, note)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (group_id, head_seq, head_hash, now.isoformat(), by.id, expected, counted_cash, note.strip()),
    )

    group = get_group(conn, group_id)
    today: date = now.date()
    sent = 0
    for member in list_members(conn, group_id):
        if not member.active:
            continue
        statement = member_statement(entries, member.id, today)
        message = t(
            "sms.meeting_closed",
            member.language,
            group=group.name,
            savings=money.fmt(statement.savings),
            loan=money.fmt(statement.loan_balance),
            fingerprint=fingerprint(head_hash),
            seq=head_seq,
            cash=_cash_line(expected, counted_cash, member.language),
        )
        sent += gateway.send(member.phone, message)
    return MeetingResult(head_seq, head_hash, fingerprint(head_hash), expected, counted_cash, sent)


def list_meetings(conn: sqlite3.Connection, group_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT c.*, m.name AS closed_by_name FROM checkpoints c JOIN members m ON m.id = c.closed_by"
        " WHERE c.group_id = ? ORDER BY c.id",
        (group_id,),
    ).fetchall()
    return [
        {
            "seq": r["seq"],
            "fingerprint": fingerprint(r["hash"]),
            "hash": r["hash"],
            "closed_at": r["closed_at"],
            "closed_by": r["closed_by_name"],
            "expected_cash": r["expected_cash"],
            "counted_cash": r["counted_cash"],
            "note": r["note"],
        }
        for r in rows
    ]
