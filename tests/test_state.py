from datetime import date

from chama.dates import add_months, months_between
from chama.ledger import Kind, verify
from chama.state import project

from .factories import ChainBuilder


def loan_data(interest, rate_bp=1000, months=3):
    return {"interest": interest, "rate_bp": rate_bp, "months": months, "method": "flat"}


def test_dates():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert months_between(date(2026, 1, 31), date(2026, 2, 28)) == 1
    assert months_between(date(2026, 1, 15), date(2026, 2, 14)) == 0
    assert months_between(date(2026, 3, 1), date(2026, 1, 1)) == 0


def test_contributions_fines_welfare_and_expenses():
    c = ChainBuilder()
    c.add(Kind.CONTRIBUTION, 100000, member_id=1)
    c.add(Kind.CONTRIBUTION, 50000, member_id=2)
    c.add(Kind.FINE, 5000, member_id=2)
    c.add(Kind.WELFARE_CONTRIBUTION, 2000, member_id=1)
    c.add(Kind.WELFARE_PAYOUT, 1500, member_id=None, approved_by=2)
    c.add(Kind.EXPENSE, 1000, approved_by=2)
    s = project(c.entries)
    assert s.member(1).savings == 100000
    assert s.member(2).fines == 5000
    assert s.total_savings == 150000
    assert s.welfare_fund == 500
    assert s.cash == 100000 + 50000 + 5000 + 2000 - 1500 - 1000
    assert s.distributable_profit == 4000
    assert verify(c.entries).ok


def test_loan_repayment_goes_to_interest_first():
    c = ChainBuilder()
    c.add(Kind.CONTRIBUTION, 300000, member_id=1)
    loan = c.add(Kind.LOAN_DISBURSEMENT, 100000, member_id=1, day="2026-01-10", data=loan_data(30000), approved_by=2)
    c.add(Kind.LOAN_REPAYMENT, 40000, member_id=1, day="2026-02-10", data={"loan": loan.seq})
    s = project(c.entries)
    state = s.loans[loan.seq]
    assert (state.interest_paid, state.principal_paid, state.outstanding) == (30000, 10000, 90000)
    assert s.interest_income == 30000
    assert s.cash == 300000 - 100000 + 40000
    assert state.due_on == date(2026, 4, 10)
    assert state.installment == 43334
    assert state.status(date(2026, 2, 11)) == "in_arrears"
    assert state.arrears(date(2026, 2, 11)) == 3334
    assert state.status(date(2026, 4, 11)) == "overdue"
    assert s.active_loans(1) == [state]


def test_cleared_loan():
    c = ChainBuilder()
    loan = c.add(Kind.LOAN_DISBURSEMENT, 10000, member_id=1, data=loan_data(1000, months=1), approved_by=2)
    c.add(Kind.LOAN_REPAYMENT, 11000, member_id=1, data={"loan": loan.seq})
    s = project(c.entries)
    assert s.loans[loan.seq].status(date(2027, 1, 1)) == "cleared"
    assert s.active_loans() == []


def test_reversed_entries_are_ignored_but_kept():
    c = ChainBuilder()
    wrong = c.add(Kind.CONTRIBUTION, 500000, member_id=1)  # typo: should be 5,000
    c.add(Kind.REVERSAL, 500000, member_id=1, data={"reverses": wrong.seq})
    c.add(Kind.CONTRIBUTION, 500000 // 100, member_id=1)
    s = project(c.entries)
    assert s.member(1).savings == 5000
    assert s.reversed == {wrong.seq}
    assert s.entries == 3


def test_share_out_returns_savings_and_profit():
    c = ChainBuilder()
    c.add(Kind.CONTRIBUTION, 100000, member_id=1)
    c.add(Kind.FINE, 2000, member_id=1)
    c.add(Kind.SHARE_OUT, 102000, member_id=1, data={"savings_returned": 100000, "profit": 2000}, approved_by=2)
    s = project(c.entries)
    assert s.member(1).savings == 0
    assert s.member(1).share_out_received == 102000
    assert s.distributable_profit == 0
    assert s.cash == 0
