import pytest

from chama import meetings, service, share_out
from chama.ledger import Kind
from chama.service import ChamaError, PermissionDenied

from .helpers import KES, seeded_group


@pytest.fixture
def c():
    ctx = seeded_group()
    g, t = ctx.group.id, ctx.treasurer
    service.contribute(ctx.conn, g, t, ctx.alice.id, 3000 * KES)
    service.contribute(ctx.conn, g, t, ctx.bob.id, 1000 * KES)
    service.welfare_contribution(ctx.conn, g, t, ctx.bob.id, 200 * KES)
    loan = service.disburse_loan(ctx.conn, g, t, ctx.chair, ctx.bob.id, 1000 * KES, 1)
    ctx.loan = loan
    return ctx


def clear_loan(c):
    service.repay_loan(c.conn, c.group.id, c.treasurer, c.loan.seq, 1100 * KES)


def test_cannot_share_out_with_active_loans(c):
    with pytest.raises(ChamaError, match="loans must be cleared"):
        share_out.preview(c.conn, c.group.id)


def test_plan_shares_profit_by_savings(c):
    clear_loan(c)
    service.fine(c.conn, c.group.id, c.treasurer, c.alice.id, 21 * KES, "Late")
    service.expense(c.conn, c.group.id, c.treasurer, c.chair, 20 * KES, "Stationery")
    plan = share_out.preview(c.conn, c.group.id)
    assert plan.profit == (100 + 21 - 20) * KES
    shares = {line.member_id: line for line in plan.lines}
    assert shares[c.alice.id].profit_share == 7575
    assert shares[c.bob.id].profit_share == 2525
    assert sum(line.profit_share for line in plan.lines) == plan.profit
    assert plan.welfare_fund_kept == 200 * KES


def test_execute_records_entries_and_empties_savings(c):
    clear_loan(c)
    with pytest.raises(PermissionDenied):
        share_out.execute(c.conn, c.group.id, c.treasurer, None)
    entries = share_out.execute(c.conn, c.group.id, c.treasurer, c.chair)
    assert [e.kind for e in entries] == [Kind.SHARE_OUT, Kind.SHARE_OUT]
    assert entries[0].prev_hash != entries[1].prev_hash
    state = service.group_state(c.conn, c.group.id)
    assert state.total_savings == 0
    assert state.cash == state.welfare_fund == 200 * KES
    assert state.distributable_profit == 0
    assert meetings.verify_group(c.conn, c.group.id).ok
    with pytest.raises(ChamaError, match="no savings"):
        share_out.preview(c.conn, c.group.id)


def test_loss_blocks_share_out(c):
    clear_loan(c)
    service.expense(c.conn, c.group.id, c.treasurer, c.chair, 4000 * KES, "Bad investment")
    with pytest.raises(ChamaError, match="expenses exceed income"):
        share_out.preview(c.conn, c.group.id)
