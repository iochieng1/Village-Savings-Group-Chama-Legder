import sqlite3

import pytest

from chama import db, security
from chama.ledger import Kind, verify

from .factories import ChainBuilder


@pytest.fixture
def conn():
    connection = db.connect()
    connection.execute("INSERT INTO groups (name) VALUES ('Umoja Women Group')")
    for phone in ("+254700000001", "+254700000002"):
        connection.execute(
            "INSERT INTO members (group_id, name, phone, pin_hash) VALUES (1, 'M', ?, ?)",
            (phone, security.hash_pin("4826")),
        )
    return connection


def test_entries_round_trip_and_still_verify(conn):
    chain = ChainBuilder()
    chain.add(Kind.CONTRIBUTION, 50000, member_id=1, data={"note": "ñ"})
    chain.add(Kind.LOAN_DISBURSEMENT, 10000, member_id=2, data={"interest": 1000, "rate_bp": 1000, "months": 1}, approved_by=2)
    for entry in chain.entries:
        db.insert_entry(conn, entry)
    loaded = db.load_entries(conn, 1)
    assert loaded == chain.entries
    assert verify(loaded).ok


@pytest.mark.parametrize("sql", ["UPDATE entries SET amount = 1", "DELETE FROM entries"])
def test_entries_are_append_only(conn, sql):
    db.insert_entry(conn, ChainBuilder().add(Kind.CONTRIBUTION, 50000, member_id=1))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(sql)


def test_amount_must_be_positive(conn):
    entry = ChainBuilder().add(Kind.CONTRIBUTION, 50000, member_id=1)
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_entry(conn, entry.__class__(**{**entry.__dict__, "amount": 0}))


def test_sequence_unique_per_group(conn):
    entry = ChainBuilder().add(Kind.CONTRIBUTION, 50000, member_id=1)
    db.insert_entry(conn, entry)
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_entry(conn, entry)
