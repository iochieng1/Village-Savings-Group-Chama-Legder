"""Member statements and the group summary, both derived from the ledger."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from .dates import entry_date
from .ledger import Entry, Kind, fingerprint
from .state import GroupState, project

# Direction of money from the member's point of view.
PAID_IN = frozenset({Kind.CONTRIBUTION, Kind.FINE, Kind.WELFARE_CONTRIBUTION, Kind.LOAN_REPAYMENT})
PAID_OUT = frozenset({Kind.LOAN_DISBURSEMENT, Kind.SHARE_OUT, Kind.WELFARE_PAYOUT})


@dataclass
class StatementLine:
    seq: int
    date: str
    kind: str
    memo: str
    external_ref: str
    paid_in: int
    paid_out: int
    savings_balance: int
    loan_balance: int
    reversed: bool
    reverses: int | None
    fingerprint: str


@dataclass
class LoanSummary:
    id: int
    principal: int
    interest: int
    paid: int
    outstanding: int
    installment: int
    arrears: int
    due_on: str
    status: str


@dataclass
class MemberStatement:
    member_id: int
    lines: list[StatementLine]
    savings: int
    fines: int
    welfare: int
    share_out_received: int
    loans: list[LoanSummary] = field(default_factory=list)

    @property
    def loan_balance(self) -> int:
        return sum(loan.outstanding for loan in self.loans)


def member_statement(entries: Iterable[Entry], member_id: int, today: date) -> MemberStatement:
    entries = list(entries)
    state = project(entries)
    savings = loan_balance = 0
    lines = []
    for e in entries:
        if e.member_id != member_id:
            continue
        kind = Kind(e.kind)
        effective = kind is not Kind.REVERSAL and e.seq not in state.reversed
        if effective:
            if kind is Kind.CONTRIBUTION:
                savings += e.amount
            elif kind is Kind.SHARE_OUT:
                savings -= e.data["savings_returned"]
            elif kind is Kind.LOAN_DISBURSEMENT:
                loan_balance += e.amount + e.data["interest"]
            elif kind is Kind.LOAN_REPAYMENT:
                loan_balance -= e.amount
        lines.append(
            StatementLine(
                seq=e.seq,
                date=entry_date(e.recorded_at).isoformat(),
                kind=e.kind,
                memo=e.memo,
                external_ref=e.external_ref,
                paid_in=e.amount if kind in PAID_IN else 0,
                paid_out=e.amount if kind in PAID_OUT else 0,
                savings_balance=savings,
                loan_balance=loan_balance,
                reversed=e.seq in state.reversed,
                reverses=e.data.get("reverses"),
                fingerprint=fingerprint(e.hash),
            )
        )
    m = state.member(member_id)
    loans = [
        LoanSummary(
            id=loan.id,
            principal=loan.principal,
            interest=loan.interest,
            paid=loan.paid,
            outstanding=loan.outstanding,
            installment=loan.installment,
            arrears=loan.arrears(today),
            due_on=loan.due_on.isoformat(),
            status=loan.status(today),
        )
        for loan in state.loans.values()
        if loan.member_id == member_id
    ]
    return MemberStatement(member_id, lines, m.savings, m.fines, m.welfare, m.share_out_received, loans)


@dataclass
class GroupSummary:
    entries: int
    members_with_activity: int
    total_savings: int
    cash_expected: int
    welfare_fund: int
    loans_outstanding: int
    active_loans: int
    overdue_loans: int
    interest_income: int
    fine_income: int
    expenses: int
    distributable_profit: int


def group_summary(state: GroupState, today: date) -> GroupSummary:
    active = state.active_loans()
    return GroupSummary(
        entries=state.entries,
        members_with_activity=len(state.members),
        total_savings=state.total_savings,
        cash_expected=state.cash,
        welfare_fund=state.welfare_fund,
        loans_outstanding=state.loans_outstanding,
        active_loans=len(active),
        overdue_loans=sum(1 for loan in active if loan.status(today) == "overdue"),
        interest_income=state.interest_income,
        fine_income=state.fine_income,
        expenses=state.expenses,
        distributable_profit=state.distributable_profit,
    )
