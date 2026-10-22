"""End-of-cycle share-out.

Savings groups commonly close a cycle by returning every member's savings plus a
share of the profit (loan interest and fines, less expenses) in proportion to
what they saved. The plan is shown to everyone before it is executed, and the
result is a set of SHARE_OUT entries in the same verifiable ledger.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import db, money
from .dates import utc_now
from .ledger import GENESIS_HASH, Entry, Kind, seal
from .service import ChamaError, Member, available_cash, require_approver, require_official
from .state import GroupState, project


@dataclass
class ShareLine:
    member_id: int
    savings: int
    profit_share: int

    @property
    def total(self) -> int:
        return self.savings + self.profit_share


@dataclass
class SharePlan:
    profit: int
    total_savings: int
    welfare_fund_kept: int
    lines: list[ShareLine]

    @property
    def total_payout(self) -> int:
        return sum(line.total for line in self.lines)


def build_plan(state: GroupState) -> SharePlan:
    if state.active_loans():
        raise ChamaError("all loans must be cleared before the share-out")
    profit = state.distributable_profit
    if profit < 0:
        raise ChamaError(f"expenses exceed income by {money.fmt(-profit)}; agree how to cover it first")
    savers = {m.member_id: m.savings for m in state.members.values() if m.savings > 0}
    if not savers:
        raise ChamaError("no savings to share out")
    shares = money.split_pro_rata(profit, savers)
    lines = [ShareLine(member_id, savings, shares[member_id]) for member_id, savings in savers.items()]
    plan = SharePlan(profit, sum(savers.values()), state.welfare_fund, lines)
    if plan.total_payout > available_cash(state):
        raise ChamaError(
            f"share-out needs {money.fmt(plan.total_payout)} but only {money.fmt(available_cash(state))} is available;"
            " reconcile the cash first"
        )
    return plan


def preview(conn: sqlite3.Connection, group_id: int) -> SharePlan:
    return build_plan(project(db.load_entries(conn, group_id)))


def execute(
    conn: sqlite3.Connection,
    group_id: int,
    by: Member,
    approver: Member | None,
    now: datetime | None = None,
) -> list[Entry]:
    require_official(by, group_id)
    require_approver(by, approver, group_id)
    recorded_at = (now or utc_now()).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        entries = db.load_entries(conn, group_id)
        plan = build_plan(project(entries))
        prev = entries[-1] if entries else None
        created = []
        for line in plan.lines:
            entry = seal(
                Entry(
                    seq=(prev.seq if prev else 0) + 1,
                    group_id=group_id,
                    kind=str(Kind.SHARE_OUT),
                    amount=line.total,
                    member_id=line.member_id,
                    recorded_by=by.id,
                    approved_by=approver.id,
                    recorded_at=recorded_at,
                    memo="End-of-cycle share-out",
                    data={"savings_returned": line.savings, "profit": line.profit_share},
                    prev_hash=prev.hash if prev else GENESIS_HASH,
                )
            )
            db.insert_entry(conn, entry)
            created.append(entry)
            prev = entry
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return created
