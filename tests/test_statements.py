from datetime import date

from chama.ledger import Kind
from chama.statements import group_summary, member_statement
from chama.state import project

from .factories import ChainBuilder

LOAN = {"interest": 3000, "rate_bp": 1000, "months": 3, "method": "flat"}


def build():
    c = ChainBuilder()
    c.add(Kind.CONTRIBUTION, 50000, member_id=1, day="2026-01-05")
    c.add(Kind.CONTRIBUTION, 40000, member_id=2, day="2026-01-05")
    wrong = c.add(Kind.CONTRIBUTION, 99999, member_id=1, day="2026-02-05")
    c.add(Kind.REVERSAL, 99999, member_id=1, day="2026-02-05", data={"reverses": wrong.seq}, approved_by=2)
    loan = c.add(Kind.LOAN_DISBURSEMENT, 10000, member_id=1, day="2026-02-05", data=LOAN, approved_by=2)
    c.add(Kind.LOAN_REPAYMENT, 5000, member_id=1, day="2026-03-05", data={"loan": loan.seq})
    c.add(Kind.FINE, 500, member_id=1, day="2026-03-05")
    c.add(Kind.EXPENSE, 1000, day="2026-03-05", approved_by=2)
    return c.entries


def test_member_statement_running_balances():
    statement = member_statement(build(), 1, date(2026, 6, 1))
    assert [line.seq for line in statement.lines] == [1, 3, 4, 5, 6, 7]
    assert [line.savings_balance for line in statement.lines] == [50000, 50000, 50000, 50000, 50000, 50000]
    assert [line.loan_balance for line in statement.lines] == [0, 0, 0, 13000, 8000, 8000]
    reversed_line, reversal_line = statement.lines[1], statement.lines[2]
    assert reversed_line.reversed and reversed_line.paid_in == 99999
    assert reversal_line.reverses == 3
    assert statement.lines[3].paid_out == 10000
    assert statement.savings == 50000 and statement.fines == 500
    [loan] = statement.loans
    assert (loan.outstanding, loan.status, loan.due_on) == (8000, "overdue", "2026-05-05")
    assert statement.loan_balance == 8000
    assert all(len(line.fingerprint) == 9 for line in statement.lines)


def test_member_without_activity():
    statement = member_statement(build(), 42, date(2026, 6, 1))
    assert statement.lines == [] and statement.savings == 0 and statement.loans == []


def test_group_summary():
    summary = group_summary(project(build()), date(2026, 6, 1))
    assert summary.entries == 8
    assert summary.total_savings == 90000
    assert summary.cash_expected == 90000 - 10000 + 5000 + 500 - 1000
    assert summary.loans_outstanding == 8000
    assert (summary.active_loans, summary.overdue_loans) == (1, 1)
    assert summary.interest_income == 3000
    assert summary.distributable_profit == 3000 + 500 - 1000
