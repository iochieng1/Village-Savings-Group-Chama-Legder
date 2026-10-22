"""SQLite storage.

Ledger entries are append-only: triggers reject any UPDATE or DELETE. Someone
with direct file access could still drop the triggers, which is why the hash
chain and the fingerprints members receive exist as the second line of defence.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .ledger import Checkpoint, Entry

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    loan_rate_bp     INTEGER NOT NULL DEFAULT 1000,  -- flat interest per month, basis points
    loan_multiplier  INTEGER NOT NULL DEFAULT 3,     -- max loan = savings x multiplier
    max_loan_months  INTEGER NOT NULL DEFAULT 6,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY,
    group_id     INTEGER NOT NULL REFERENCES groups(id),
    name         TEXT NOT NULL,
    phone        TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member',
    language     TEXT NOT NULL DEFAULT 'en',
    pin_hash     TEXT NOT NULL,
    failed_pins  INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    joined_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (group_id, phone)
);

CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY,
    group_id      INTEGER NOT NULL REFERENCES groups(id),
    seq           INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    amount        INTEGER NOT NULL CHECK (amount > 0),
    member_id     INTEGER REFERENCES members(id),
    recorded_by   INTEGER NOT NULL REFERENCES members(id),
    approved_by   INTEGER REFERENCES members(id),
    recorded_at   TEXT NOT NULL,
    memo          TEXT NOT NULL DEFAULT '',
    external_ref  TEXT NOT NULL DEFAULT '',
    data          TEXT NOT NULL DEFAULT '{}',
    prev_hash     TEXT NOT NULL,
    hash          TEXT NOT NULL,
    UNIQUE (group_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_entries_member ON entries(group_id, member_id);

CREATE TRIGGER IF NOT EXISTS entries_no_update BEFORE UPDATE ON entries
BEGIN SELECT RAISE(ABORT, 'ledger entries are append-only; record a reversal instead'); END;
CREATE TRIGGER IF NOT EXISTS entries_no_delete BEFORE DELETE ON entries
BEGIN SELECT RAISE(ABORT, 'ledger entries are append-only; record a reversal instead'); END;

CREATE TABLE IF NOT EXISTS checkpoints (
    id         INTEGER PRIMARY KEY,
    group_id   INTEGER NOT NULL REFERENCES groups(id),
    seq        INTEGER NOT NULL,
    hash       TEXT NOT NULL,
    closed_at  TEXT NOT NULL,
    closed_by  INTEGER NOT NULL REFERENCES members(id),
    expected_cash INTEGER NOT NULL,
    counted_cash  INTEGER,
    note       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS acknowledgements (
    id         INTEGER PRIMARY KEY,
    entry_id   INTEGER NOT NULL REFERENCES entries(id),
    member_id  INTEGER NOT NULL REFERENCES members(id),
    status     TEXT NOT NULL CHECK (status IN ('confirmed', 'disputed')),
    note       TEXT NOT NULL DEFAULT '',
    at         TEXT NOT NULL,
    UNIQUE (entry_id, member_id)
);
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    # Autocommit mode: writers open explicit transactions where atomicity matters.
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def row_to_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        seq=row["seq"],
        group_id=row["group_id"],
        kind=row["kind"],
        amount=row["amount"],
        member_id=row["member_id"],
        recorded_by=row["recorded_by"],
        approved_by=row["approved_by"],
        recorded_at=row["recorded_at"],
        memo=row["memo"],
        external_ref=row["external_ref"],
        data=json.loads(row["data"]),
        prev_hash=row["prev_hash"],
        hash=row["hash"],
    )


def load_entries(conn: sqlite3.Connection, group_id: int) -> list[Entry]:
    rows = conn.execute("SELECT * FROM entries WHERE group_id = ? ORDER BY seq", (group_id,)).fetchall()
    return [row_to_entry(r) for r in rows]


def load_checkpoints(conn: sqlite3.Connection, group_id: int) -> list[Checkpoint]:
    rows = conn.execute("SELECT seq, hash, closed_at FROM checkpoints WHERE group_id = ? ORDER BY id", (group_id,))
    return [Checkpoint(r["seq"], r["hash"], r["closed_at"]) for r in rows.fetchall()]


def insert_entry(conn: sqlite3.Connection, entry: Entry) -> None:
    conn.execute(
        "INSERT INTO entries (group_id, seq, kind, amount, member_id, recorded_by, approved_by, recorded_at,"
        " memo, external_ref, data, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry.group_id,
            entry.seq,
            entry.kind,
            entry.amount,
            entry.member_id,
            entry.recorded_by,
            entry.approved_by,
            entry.recorded_at,
            entry.memo,
            entry.external_ref,
            json.dumps(entry.data, sort_keys=True),
            entry.prev_hash,
            entry.hash,
        ),
    )
