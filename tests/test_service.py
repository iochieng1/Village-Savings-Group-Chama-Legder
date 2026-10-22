import sqlite3
from datetime import datetime, timezone

import pytest

from chama import db, service
from chama.ledger import Kind, verify
from chama.service import AuthError, ChamaError, PermissionDenied

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
KES = 100  # cents per shilling


@pytest.fixture
def chama():
    conn = db.connect()
    group, chair = service.create_group(conn, "Umoja Women Group", "Achieng", "0700000001", "4826")
    treasurer = service.add_member(conn, group.id, chair, "Wanjiru", "0700000002", "5937", role="treasurer")
    alice = service.add_member(conn, group.id, chair, "Akinyi", "0700000003", "7193")
    bob = service.add_member(conn, group.id, treasurer, "Barasa", "0700000004", "2468")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.conn, ctx.group, ctx.chair, ctx.treasurer, ctx.alice, ctx.bob = conn, group, chair, treasurer, alice, bob
    return ctx


def save(c, member, shillings, ref=""):
    return service.contribute(c.conn, c.group.id, c.treasurer, member.id, shillings * KES, external_ref=ref, now=NOW)


def test_create_group_defaults(chama):
    assert chama.chair.role == "chair"
    assert chama.chair.phone == "+254700000001"
    assert (chama.group.loan_rate_bp, chama.group.loan_multiplier, chama.group.max_loan_months) == (1000, 3, 6)
    assert [m.name for m in service.list_members(chama.conn, chama.group.id)] == ["Achieng", "Wanjiru", "Akinyi", "Barasa"]


def test_member_management_rules(chama):
    c = chama
    with pytest.raises(PermissionDenied):
        service.add_member(c.conn, c.group.id, c.alice, "X", "0700000009", "4826")
    with pytest.raises(PermissionDenied, match="chair"):
        service.add_member(c.conn, c.group.id, c.treasurer, "X", "0700000009", "4826", role="secretary")
    with pytest.raises(ChamaError, match="already exists"):
        service.add_member(c.conn, c.group.id, c.chair, "X", "0700000003", "4826")
    with pytest.raises(ChamaError, match="role"):
        service.add_member(c.conn, c.group.id, c.chair, "X", "0700000009", "4826", role="boss")


def test_authenticate_and_lockout(chama):
    c = chama
    assert service.authenticate(c.conn, c.group.id, "0700000003", "7193").id == c.alice.id
    for _ in range(5):
        with pytest.raises(AuthError, match="wrong"):
            service.authenticate(c.conn, c.group.id, "0700000003", "0000")
    with pytest.raises(AuthError, match="locked"):
        service.authenticate(c.conn, c.group.id, "0700000003", "7193")
    with pytest.raises(PermissionDenied):
        service.reset_pin(c.conn, c.group.id, c.treasurer, c.alice.id, "8642")
    service.reset_pin(c.conn, c.group.id, c.chair, c.alice.id, "8642")
    assert service.authenticate(c.conn, c.group.id, "0700000003", "8642")
    with pytest.raises(AuthError):
        service.authenticate(c.conn, c.group.id, "not-a-phone", "8642")


def test_failed_pin_counter_resets_on_success(chama):
    c = chama
    for _ in range(4):
        with pytest.raises(AuthError):
            service.authenticate(c.conn, c.group.id, "0700000003", "0000")
    service.authenticate(c.conn, c.group.id, "0700000003", "7193")
    with pytest.raises(AuthError, match="wrong"):
        service.authenticate(c.conn, c.group.id, "0700000003", "0000")


def test_only_officials_record(chama):
    with pytest.raises(PermissionDenied):
        service.contribute(chama.conn, chama.group.id, chama.alice, chama.alice.id, 100 * KES)


def test_contributions_chain_and_receipt_dedup(chama):
    c = chama
    first = save(c, c.alice, 1000, ref="sjk2abc123")
    second = save(c, c.bob, 500)
    assert (first.seq, second.seq) == (1, 2)
    assert second.prev_hash == first.hash
    assert first.external_ref == "SJK2ABC123"
    with pytest.raises(ChamaError, match="already recorded as entry #1"):
        save(c, c.bob, 1000, ref="SJK2ABC123")
    assert verify(db.load_entries(c.conn, c.group.id)).ok


def test_fine_needs_reason(chama):
    with pytest.raises(ChamaError, match="reason"):
        service.fine(chama.conn, chama.group.id, chama.treasurer, chama.bob.id, 50 * KES, " ")


def test_loan_rules(chama):
    c = chama
    save(c, c.alice, 1000)
    save(c, c.bob, 5000)
    disburse = lambda principal, months=3, approver=c.chair: service.disburse_loan(  # noqa: E731
        c.conn, c.group.id, c.treasurer, approver, c.alice.id, principal * KES, months, now=NOW
    )
    with pytest.raises(PermissionDenied, match="second official"):
        disburse(1000, approver=None)
    with pytest.raises(PermissionDenied, match="different"):
        disburse(1000, approver=c.treasurer)
    with pytest.raises(PermissionDenied):
        disburse(1000, approver=c.bob)
    with pytest.raises(ChamaError, match="limit is KES 3,000"):
        disburse(3001)
    with pytest.raises(ChamaError, match="period"):
        disburse(1000, months=7)

    loan = disburse(3000)
    assert loan.data == {"rate_bp": 1000, "months": 3, "method": "flat", "interest": 900 * KES}
    with pytest.raises(ChamaError, match="active loan"):
        disburse(100)


def test_cannot_lend_more_than_cash(chama):
    c = chama
    save(c, c.alice, 1000)
    service.welfare_contribution(c.conn, c.group.id, c.treasurer, c.bob.id, 200 * KES)
    with pytest.raises(ChamaError, match="KES 1,000 is available"):
        service.disburse_loan(c.conn, c.group.id, c.treasurer, c.chair, c.alice.id, 1100 * KES, 1)


def test_repayment_rules(chama):
    c = chama
    save(c, c.alice, 1000)
    loan = service.disburse_loan(c.conn, c.group.id, c.treasurer, c.chair, c.alice.id, 1000 * KES, 1, now=NOW)
    with pytest.raises(ChamaError, match="more than the KES 1,100"):
        service.repay_loan(c.conn, c.group.id, c.treasurer, loan.seq, 1200 * KES)
    repayment = service.repay_loan(c.conn, c.group.id, c.treasurer, loan.seq, 1100 * KES)
    assert repayment.member_id == c.alice.id
    with pytest.raises(ChamaError, match="cleared"):
        service.repay_loan(c.conn, c.group.id, c.treasurer, loan.seq, 1 * KES)
    with pytest.raises(ChamaError, match="not found"):
        service.repay_loan(c.conn, c.group.id, c.treasurer, 99, 1 * KES)


def test_expense_and_welfare_payout(chama):
    c = chama
    save(c, c.alice, 1000)
    service.welfare_contribution(c.conn, c.group.id, c.treasurer, c.alice.id, 300 * KES)
    with pytest.raises(ChamaError, match="describe"):
        service.expense(c.conn, c.group.id, c.treasurer, c.chair, 100 * KES, "")
    with pytest.raises(ChamaError, match="available"):
        service.expense(c.conn, c.group.id, c.treasurer, c.chair, 1100 * KES, "Hall hire")
    service.expense(c.conn, c.group.id, c.treasurer, c.chair, 100 * KES, "Hall hire")
    with pytest.raises(ChamaError, match="welfare fund has only KES 300"):
        service.welfare_payout(c.conn, c.group.id, c.treasurer, c.chair, 400 * KES, "Hospital bill", member_id=c.bob.id)
    service.welfare_payout(c.conn, c.group.id, c.treasurer, c.chair, 300 * KES, "Hospital bill", member_id=c.bob.id)
    state = service.group_state(c.conn, c.group.id)
    assert (state.cash, state.welfare_fund, state.expenses) == (900 * KES, 0, 100 * KES)


def test_reversal_rules(chama):
    c = chama
    wrong = save(c, c.alice, 10000, ref="QWE123")
    with pytest.raises(PermissionDenied):
        service.reverse(c.conn, c.group.id, c.treasurer, None, wrong.seq, "Typo")
    with pytest.raises(ChamaError, match="reason"):
        service.reverse(c.conn, c.group.id, c.treasurer, c.chair, wrong.seq, "")
    reversal = service.reverse(c.conn, c.group.id, c.treasurer, c.chair, wrong.seq, "Typo: was KES 1,000")
    assert (reversal.kind, reversal.amount, reversal.member_id, reversal.data) == (
        "reversal", wrong.amount, c.alice.id, {"reverses": wrong.seq}
    )
    with pytest.raises(ChamaError, match="already reversed"):
        service.reverse(c.conn, c.group.id, c.treasurer, c.chair, wrong.seq, "again")
    with pytest.raises(ChamaError, match="cannot be reversed"):
        service.reverse(c.conn, c.group.id, c.treasurer, c.chair, reversal.seq, "undo")
    with pytest.raises(ChamaError, match="not found"):
        service.reverse(c.conn, c.group.id, c.treasurer, c.chair, 99, "x")
    # The receipt can be recorded again correctly once the mistake is reversed.
    save(c, c.alice, 1000, ref="QWE123")
    assert service.group_state(c.conn, c.group.id).member(c.alice.id).savings == 1000 * KES


def test_loan_with_repayments_cannot_be_reversed(chama):
    c = chama
    save(c, c.alice, 1000)
    loan = service.disburse_loan(c.conn, c.group.id, c.treasurer, c.chair, c.alice.id, 500 * KES, 1)
    service.repay_loan(c.conn, c.group.id, c.treasurer, loan.seq, 100 * KES)
    with pytest.raises(ChamaError, match="repayments first"):
        service.reverse(c.conn, c.group.id, c.treasurer, c.chair, loan.seq, "Wrong member")


def test_failed_operation_leaves_ledger_unchanged(chama):
    c = chama
    save(c, c.alice, 100)
    with pytest.raises(ChamaError):
        service.disburse_loan(c.conn, c.group.id, c.treasurer, c.chair, c.alice.id, 1000 * KES, 1)
    assert len(db.load_entries(c.conn, c.group.id)) == 1
    with pytest.raises(sqlite3.IntegrityError):
        c.conn.execute("DELETE FROM entries")


def test_member_from_other_group_rejected(chama):
    c = chama
    other_group, other_chair = service.create_group(c.conn, "Other", "Otieno", "0700000010", "4826")
    with pytest.raises(PermissionDenied):
        service.contribute(c.conn, c.group.id, other_chair, c.alice.id, 100 * KES)
    with pytest.raises(ChamaError, match="not an active member"):
        service.contribute(c.conn, c.group.id, c.treasurer, other_chair.id, 100 * KES)
