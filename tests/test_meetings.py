from datetime import datetime, timezone

import pytest

from chama import db, ledger, meetings, service
from chama.service import ChamaError, PermissionDenied
from chama.sms import ConsoleGateway

from .helpers import KES, seeded_group

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def c():
    ctx = seeded_group()
    service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.alice.id, 1000 * KES)
    service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.bob.id, 500 * KES)
    loan = service.disburse_loan(ctx.conn, ctx.group.id, ctx.treasurer, ctx.chair, ctx.bob.id, 1000 * KES, 2)
    ctx.loan = loan
    return ctx


def test_close_meeting_sends_personal_balances_and_fingerprint(c):
    gateway = ConsoleGateway()
    result = meetings.close_meeting(c.conn, c.group.id, c.treasurer, gateway, counted_cash=400 * KES, now=NOW)
    assert result.seq == 3
    assert result.fingerprint == ledger.fingerprint(c.loan.hash)
    assert (result.expected_cash, result.cash_difference) == (500 * KES, -100 * KES)
    assert result.sms_sent == 4

    messages = dict(gateway.outbox)
    assert "Akiba yako: KES 1,000" in messages["+254700000003"]
    assert "Pesa ZIMEPUNGUA kwa KES 100" in messages["+254700000003"]
    bob = messages["+254700000004"]
    assert "Loan balance: KES 1,200" in bob
    assert result.fingerprint in bob and "#3" in bob

    [meeting] = meetings.list_meetings(c.conn, c.group.id)
    assert (meeting["closed_by"], meeting["counted_cash"], meeting["fingerprint"]) == ("Wanjiru", 400 * KES, result.fingerprint)


def test_balanced_and_uncounted_cash(c):
    gateway = ConsoleGateway()
    meetings.close_meeting(c.conn, c.group.id, c.chair, gateway, counted_cash=500 * KES)
    assert "Cash count balanced" in gateway.outbox[0][1]
    gateway.outbox.clear()
    meetings.close_meeting(c.conn, c.group.id, c.chair, gateway)
    assert "Cash" not in gateway.outbox[0][1]


def test_only_officials_close(c):
    with pytest.raises(PermissionDenied):
        meetings.close_meeting(c.conn, c.group.id, c.alice, ConsoleGateway())
    with pytest.raises(ChamaError, match="negative"):
        meetings.close_meeting(c.conn, c.group.id, c.chair, ConsoleGateway(), counted_cash=-1)


def test_empty_group_can_close():
    ctx = seeded_group()
    result = meetings.close_meeting(ctx.conn, ctx.group.id, ctx.chair, ConsoleGateway())
    assert result.seq == 0
    assert meetings.verify_group(ctx.conn, ctx.group.id).ok


def tamper(conn, sql, params=()):
    """Simulate someone with direct database access bypassing the triggers."""
    conn.execute("DROP TRIGGER entries_no_update")
    conn.execute(sql, params)


def test_direct_database_edit_is_detected(c):
    meetings.close_meeting(c.conn, c.group.id, c.chair, ConsoleGateway())
    tamper(c.conn, "UPDATE entries SET amount = 100 WHERE seq = 1")
    result = meetings.verify_group(c.conn, c.group.id)
    assert not result.ok and result.broken_at == 1
    with pytest.raises(ChamaError, match="failed verification at entry #1"):
        meetings.close_meeting(c.conn, c.group.id, c.chair, ConsoleGateway())


def test_resealed_forgery_detected_by_members_fingerprints(c):
    meetings.close_meeting(c.conn, c.group.id, c.chair, ConsoleGateway())
    # Forger rewrites Alice's savings and recomputes every hash after it.
    entries = db.load_entries(c.conn, c.group.id)
    forged, prev = [], ledger.GENESIS_HASH
    for e in entries:
        amount = 10 * KES if e.seq == 1 else e.amount
        new = ledger.seal(ledger.Entry(**{**e.hashed_fields(), "amount": amount, "prev_hash": prev}))
        forged.append(new)
        prev = new.hash
    tamper(c.conn, "SELECT 1")
    for e in forged:
        c.conn.execute("UPDATE entries SET amount = ?, prev_hash = ?, hash = ? WHERE seq = ?", (e.amount, e.prev_hash, e.hash, e.seq))

    result = meetings.verify_group(c.conn, c.group.id)
    assert not result.ok
    assert result.broken_at == 3
    assert "fingerprint" in result.reason
