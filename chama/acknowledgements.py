"""Members confirm or dispute the entries recorded about them.

Each member gets an SMS receipt the moment something is recorded in their name,
and can confirm it or raise a dispute. Disputes are visible to the whole group,
so a wrong record cannot sit unnoticed until the end of the cycle.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import db, money
from .dates import utc_now
from .i18n import t
from .ledger import Entry, fingerprint
from .service import ChamaError, Group, Member, PermissionDenied
from .sms import SmsGateway
from .state import reversed_seqs

CONFIRMED = "confirmed"
DISPUTED = "disputed"


@dataclass
class Acknowledgement:
    seq: int
    member_id: int
    member_name: str
    status: str
    note: str
    at: str


def _entry_row(conn: sqlite3.Connection, group_id: int, seq: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM entries WHERE group_id = ? AND seq = ?", (group_id, seq)).fetchone()
    if row is None:
        raise ChamaError(f"entry #{seq} not found")
    return row


def acknowledge(
    conn: sqlite3.Connection,
    group_id: int,
    member: Member,
    seq: int,
    status: str,
    note: str = "",
    now: datetime | None = None,
) -> Acknowledgement:
    if status not in (CONFIRMED, DISPUTED):
        raise ChamaError("status must be 'confirmed' or 'disputed'")
    if status == DISPUTED and not note.strip():
        raise ChamaError("explain what is wrong with the entry")
    if member.group_id != group_id or not member.active:
        raise PermissionDenied("not a member of this group")
    row = _entry_row(conn, group_id, seq)
    if row["member_id"] != member.id:
        raise PermissionDenied("you can only confirm or dispute entries recorded in your name")
    at = (now or utc_now()).isoformat()
    conn.execute(
        "INSERT INTO acknowledgements (entry_id, member_id, status, note, at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (entry_id, member_id) DO UPDATE SET status = excluded.status, note = excluded.note, at = excluded.at",
        (row["id"], member.id, status, note.strip(), at),
    )
    return Acknowledgement(seq, member.id, member.name, status, note.strip(), at)


def for_group(conn: sqlite3.Connection, group_id: int) -> dict[int, Acknowledgement]:
    rows = conn.execute(
        "SELECT e.seq, a.member_id, m.name, a.status, a.note, a.at FROM acknowledgements a"
        " JOIN entries e ON e.id = a.entry_id JOIN members m ON m.id = a.member_id"
        " WHERE e.group_id = ? ORDER BY e.seq",
        (group_id,),
    ).fetchall()
    return {r["seq"]: Acknowledgement(r["seq"], r["member_id"], r["name"], r["status"], r["note"], r["at"]) for r in rows}


def open_disputes(conn: sqlite3.Connection, group_id: int) -> list[Acknowledgement]:
    """Disputed entries that have not been corrected by a reversal."""
    reversed_ = reversed_seqs(db.load_entries(conn, group_id))
    return [a for a in for_group(conn, group_id).values() if a.status == DISPUTED and a.seq not in reversed_]


def pending(conn: sqlite3.Connection, group_id: int, member_id: int) -> list[int]:
    """Entries about the member they have not yet confirmed or disputed."""
    rows = conn.execute(
        "SELECT e.seq FROM entries e LEFT JOIN acknowledgements a ON a.entry_id = e.id AND a.member_id = e.member_id"
        " WHERE e.group_id = ? AND e.member_id = ? AND a.id IS NULL ORDER BY e.seq",
        (group_id, member_id),
    ).fetchall()
    return [r["seq"] for r in rows]


def send_receipt(gateway: SmsGateway, group: Group, member: Member, entry: Entry) -> bool:
    return gateway.send(
        member.phone,
        t(
            "sms.entry_recorded",
            member.language,
            group=group.name,
            kind=t(f"kind.{entry.kind}", member.language),
            amount=money.fmt(entry.amount),
            seq=entry.seq,
            fingerprint=fingerprint(entry.hash),
        ),
    )
