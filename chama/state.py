"""Replay the ledger into balances.

Balances are never stored; they are always recomputed from the entries. Any
member who holds a copy of the ledger gets exactly the same numbers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from .dates import add_months, entry_date, months_between
from .ledger import MONEY_IN, MONEY_OUT, Entry, Kind


@dataclass
class LoanState:
    id: int  # seq of the disbursement entry
    member_id: int
    principal: int
    interest: int
    rate_bp: int
    months: int
    issued_on: date
    interest_paid: int = 0
    principal_paid: int = 0
    repayments: list[int] = field(default_factory=list)

    @property
    def due_on(self) -> date:
        return add_months(self.issued_on, self.months)

    @property
    def total_due(self) -> int:
        return self.principal + self.interest

    @property
    def paid(self) -> int:
        return self.interest_paid + self.principal_paid

    @property
    def outstanding(self) -> int:
        return self.total_due - self.paid

    @property
    def installment(self) -> int:
        return -(-self.total_due // self.months)  # ceiling division

    def expected_paid(self, today: date) -> int:
        elapsed = months_between(self.issued_on, today)
        return min(self.total_due, self.installment * elapsed)

    def arrears(self, today: date) -> int:
        return max(0, self.expected_paid(today) - self.paid)

    def status(self, today: date) -> str:
        if self.outstanding == 0:
            return "cleared"
        if today > self.due_on:
            return "overdue"
        return "in_arrears" if self.arrears(today) else "current"

    def apply_repayment(self, amount: int, seq: int) -> None:
        to_interest = min(amount, self.interest - self.interest_paid)
        self.interest_paid += to_interest
        self.principal_paid += amount - to_interest
        self.repayments.append(seq)


@dataclass
class MemberState:
    member_id: int
    savings: int = 0
    fines: int = 0
    welfare: int = 0
    share_out_received: int = 0


@dataclass
class GroupState:
    members: dict[int, MemberState] = field(default_factory=dict)
    loans: dict[int, LoanState] = field(default_factory=dict)
    cash: int = 0
    welfare_fund: int = 0
    interest_income: int = 0
    fine_income: int = 0
    expenses: int = 0
    profit_shared: int = 0
    reversed: set[int] = field(default_factory=set)
    entries: int = 0

    def member(self, member_id: int) -> MemberState:
        return self.members.setdefault(member_id, MemberState(member_id))

    def active_loans(self, member_id: int | None = None) -> list[LoanState]:
        return [
            loan
            for loan in self.loans.values()
            if loan.outstanding > 0 and (member_id is None or loan.member_id == member_id)
        ]

    @property
    def total_savings(self) -> int:
        return sum(m.savings for m in self.members.values())

    @property
    def loans_outstanding(self) -> int:
        return sum(loan.outstanding for loan in self.loans.values())

    @property
    def distributable_profit(self) -> int:
        """Interest and fines earned, less expenses and profit already shared out."""
        return self.interest_income + self.fine_income - self.expenses - self.profit_shared


def reversed_seqs(entries: Iterable[Entry]) -> set[int]:
    return {e.data["reverses"] for e in entries if e.kind == Kind.REVERSAL}


def project(entries: Iterable[Entry]) -> GroupState:
    entries = list(entries)
    state = GroupState(reversed=reversed_seqs(entries), entries=len(entries))
    for e in entries:
        if e.kind == Kind.REVERSAL or e.seq in state.reversed:
            continue
        kind = Kind(e.kind)
        if kind in MONEY_IN:
            state.cash += e.amount
        elif kind in MONEY_OUT:
            state.cash -= e.amount

        if kind is Kind.CONTRIBUTION:
            state.member(e.member_id).savings += e.amount
        elif kind is Kind.FINE:
            state.member(e.member_id).fines += e.amount
            state.fine_income += e.amount
        elif kind is Kind.WELFARE_CONTRIBUTION:
            state.member(e.member_id).welfare += e.amount
            state.welfare_fund += e.amount
        elif kind is Kind.WELFARE_PAYOUT:
            state.welfare_fund -= e.amount
        elif kind is Kind.EXPENSE:
            state.expenses += e.amount
        elif kind is Kind.LOAN_DISBURSEMENT:
            state.member(e.member_id)
            state.loans[e.seq] = LoanState(
                id=e.seq,
                member_id=e.member_id,
                principal=e.amount,
                interest=e.data["interest"],
                rate_bp=e.data["rate_bp"],
                months=e.data["months"],
                issued_on=entry_date(e.recorded_at),
            )
        elif kind is Kind.LOAN_REPAYMENT:
            loan = state.loans[e.data["loan"]]
            before = loan.interest_paid
            loan.apply_repayment(e.amount, e.seq)
            state.interest_income += loan.interest_paid - before
        elif kind is Kind.SHARE_OUT:
            member = state.member(e.member_id)
            member.savings -= e.data["savings_returned"]
            member.share_out_received += e.amount
            state.profit_shared += e.data["profit"]
    return state
