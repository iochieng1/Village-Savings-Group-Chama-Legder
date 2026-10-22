"""Group operations and the rules that protect members' money.

Every money operation appends one ledger entry. The rules that need current
balances (loan limits, available cash, outstanding amounts) are checked inside
the same write lock as the append, against a fresh replay of the ledger, so two
simultaneous requests cannot both spend the same shilling.

Trust rules:
- only officials (chair, treasurer, secretary) record entries;
- money leaving the group and reversals need a second, different official;
- mistakes are reversed with a reason, never edited;
- an M-Pesa receipt code can only be recorded once.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from . import db, money, security
from .dates import utc_now
from .ledger import GENESIS_HASH, MEMBER_KINDS, MONEY_OUT, Entry, Kind, seal
from .phone import normalise
from .state import GroupState, project

OFFICIAL_ROLES = frozenset({"chair", "treasurer", "secretary"})
ROLES = OFFICIAL_ROLES | {"member"}


class ChamaError(ValueError):
    pass


class PermissionDenied(ChamaError):
    pass


class AuthError(ChamaError):
    pass


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    loan_rate_bp: int
    loan_multiplier: int
    max_loan_months: int


@dataclass(frozen=True)
class Member:
    id: int
    group_id: int
    name: str
    phone: str
    role: str
    language: str
    active: bool

    @property
    def is_official(self) -> bool:
        return self.role in OFFICIAL_ROLES


def _group(row: sqlite3.Row) -> Group:
    return Group(row["id"], row["name"], row["loan_rate_bp"], row["loan_multiplier"], row["max_loan_months"])


def _member(row: sqlite3.Row) -> Member:
    return Member(row["id"], row["group_id"], row["name"], row["phone"], row["role"], row["language"], bool(row["active"]))


# Groups and members


def create_group(
    conn: sqlite3.Connection,
    name: str,
    chair_name: str,
    chair_phone: str,
    chair_pin: str,
    loan_rate_bp: int = 1000,
    loan_multiplier: int = 3,
    max_loan_months: int = 6,
) -> tuple[Group, Member]:
    if not name.strip():
        raise ChamaError("group name is required")
    if not (0 <= loan_rate_bp <= 5000 and 1 <= loan_multiplier <= 10 and 1 <= max_loan_months <= 36):
        raise ChamaError("loan rules out of range")
    pin_hash = security.hash_pin(chair_pin)
    phone = normalise(chair_phone)
    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            "INSERT INTO groups (name, loan_rate_bp, loan_multiplier, max_loan_months) VALUES (?, ?, ?, ?)",
            (name.strip(), loan_rate_bp, loan_multiplier, max_loan_months),
        )
        group_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO members (group_id, name, phone, role, pin_hash) VALUES (?, ?, ?, 'chair', ?)",
            (group_id, chair_name.strip(), phone, pin_hash),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_group(conn, group_id), get_member(conn, cur.lastrowid)


def get_group(conn: sqlite3.Connection, group_id: int) -> Group:
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    if row is None:
        raise ChamaError(f"group {group_id} not found")
    return _group(row)


def get_member(conn: sqlite3.Connection, member_id: int) -> Member:
    row = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    if row is None:
        raise ChamaError(f"member {member_id} not found")
    return _member(row)


def list_members(conn: sqlite3.Connection, group_id: int) -> list[Member]:
    rows = conn.execute("SELECT * FROM members WHERE group_id = ? ORDER BY id", (group_id,)).fetchall()
    return [_member(r) for r in rows]


def find_member(conn: sqlite3.Connection, group_id: int, phone: str) -> Member | None:
    row = conn.execute(
        "SELECT * FROM members WHERE group_id = ? AND phone = ?", (group_id, normalise(phone))
    ).fetchone()
    return _member(row) if row else None


def add_member(
    conn: sqlite3.Connection,
    group_id: int,
    by: Member,
    name: str,
    phone: str,
    pin: str,
    role: str = "member",
    language: str = "en",
) -> Member:
    _require_official(by, group_id)
    if role not in ROLES:
        raise ChamaError(f"unknown role {role!r}")
    if role in OFFICIAL_ROLES and by.role != "chair":
        raise PermissionDenied("only the chair can add officials")
    if not name.strip():
        raise ChamaError("member name is required")
    phone = normalise(phone)
    if find_member(conn, group_id, phone):
        raise ChamaError("a member with this phone number already exists")
    cur = conn.execute(
        "INSERT INTO members (group_id, name, phone, role, language, pin_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (group_id, name.strip(), phone, role, "sw" if language == "sw" else "en", security.hash_pin(pin)),
    )
    return get_member(conn, cur.lastrowid)


def authenticate(conn: sqlite3.Connection, group_id: int, phone: str, pin: str) -> Member:
    try:
        row = conn.execute(
            "SELECT * FROM members WHERE group_id = ? AND phone = ?", (group_id, normalise(phone))
        ).fetchone()
    except ValueError:
        row = None
    if row is None or not row["active"]:
        raise AuthError("wrong phone number or PIN")
    if row["failed_pins"] >= security.MAX_FAILED_ATTEMPTS:
        raise AuthError("account locked after too many wrong PINs; ask the chair to reset it")
    if not security.check_pin(pin, row["pin_hash"]):
        conn.execute("UPDATE members SET failed_pins = failed_pins + 1 WHERE id = ?", (row["id"],))
        raise AuthError("wrong phone number or PIN")
    if row["failed_pins"]:
        conn.execute("UPDATE members SET failed_pins = 0 WHERE id = ?", (row["id"],))
    return _member(row)


def reset_pin(conn: sqlite3.Connection, group_id: int, by: Member, member_id: int, new_pin: str) -> None:
    if by.role != "chair" or by.group_id != group_id:
        raise PermissionDenied("only the chair can reset PINs")
    target = get_member(conn, member_id)
    if target.group_id != group_id:
        raise ChamaError("member is not in this group")
    conn.execute(
        "UPDATE members SET pin_hash = ?, failed_pins = 0 WHERE id = ?", (security.hash_pin(new_pin), member_id)
    )


# Ledger operations


def _require_official(member: Member, group_id: int) -> None:
    if member.group_id != group_id or not member.active or not member.is_official:
        raise PermissionDenied("only an active official of this group can do this")


def _require_approver(recorder: Member, approver: Member | None, group_id: int) -> None:
    if approver is None:
        raise PermissionDenied("a second official must approve this")
    _require_official(approver, group_id)
    if approver.id == recorder.id:
        raise PermissionDenied("the approving official must be a different person")


def _require_group_member(conn: sqlite3.Connection, group_id: int, member_id: int) -> Member:
    member = get_member(conn, member_id)
    if member.group_id != group_id or not member.active:
        raise ChamaError("member is not an active member of this group")
    return member


def _append(
    conn: sqlite3.Connection,
    group_id: int,
    kind: Kind,
    amount: int,
    recorded_by: Member,
    member_id: int | None = None,
    approved_by: Member | None = None,
    memo: str = "",
    external_ref: str = "",
    data: dict | None = None,
    now: datetime | None = None,
    check: Callable[[GroupState, list[Entry]], dict | None] | None = None,
) -> Entry:
    _require_official(recorded_by, group_id)
    if kind in MONEY_OUT or kind is Kind.REVERSAL:
        _require_approver(recorded_by, approved_by, group_id)
    if kind in MEMBER_KINDS:
        if member_id is None:
            raise ChamaError(f"{kind} must be for a member")
        _require_group_member(conn, group_id, member_id)
    if amount <= 0:
        raise ChamaError("amount must be positive")
    external_ref = external_ref.strip().upper()

    conn.execute("BEGIN IMMEDIATE")
    try:
        entries = db.load_entries(conn, group_id)
        state = project(entries)
        if external_ref:
            for e in entries:
                if e.external_ref == external_ref and e.seq not in state.reversed:
                    raise ChamaError(f"receipt {external_ref} is already recorded as entry #{e.seq}")
        extra = check(state, entries) if check else None
        last = entries[-1] if entries else None
        entry = seal(
            Entry(
                seq=(last.seq if last else 0) + 1,
                group_id=group_id,
                kind=str(kind),
                amount=amount,
                member_id=member_id,
                recorded_by=recorded_by.id,
                approved_by=approved_by.id if approved_by else None,
                recorded_at=(now or utc_now()).isoformat(),
                memo=memo.strip(),
                external_ref=external_ref,
                data={**(data or {}), **(extra or {})},
                prev_hash=last.hash if last else GENESIS_HASH,
            )
        )
        db.insert_entry(conn, entry)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return entry


def available_cash(state: GroupState) -> int:
    """Cash the group can lend or spend; the welfare fund is ring-fenced."""
    return state.cash - state.welfare_fund


def contribute(conn, group_id: int, by: Member, member_id: int, amount: int, memo: str = "", external_ref: str = "", now=None) -> Entry:
    return _append(conn, group_id, Kind.CONTRIBUTION, amount, by, member_id, memo=memo, external_ref=external_ref, now=now)


def fine(conn, group_id: int, by: Member, member_id: int, amount: int, memo: str, external_ref: str = "", now=None) -> Entry:
    if not memo.strip():
        raise ChamaError("give the reason for the fine")
    return _append(conn, group_id, Kind.FINE, amount, by, member_id, memo=memo, external_ref=external_ref, now=now)


def welfare_contribution(conn, group_id: int, by: Member, member_id: int, amount: int, memo: str = "", external_ref: str = "", now=None) -> Entry:
    return _append(conn, group_id, Kind.WELFARE_CONTRIBUTION, amount, by, member_id, memo=memo, external_ref=external_ref, now=now)


def loan_limit(state: GroupState, group: Group, member_id: int) -> int:
    savings = state.members.get(member_id).savings if member_id in state.members else 0
    return savings * group.loan_multiplier


def disburse_loan(
    conn,
    group_id: int,
    by: Member,
    approver: Member | None,
    member_id: int,
    principal: int,
    months: int,
    memo: str = "",
    external_ref: str = "",
    now=None,
) -> Entry:
    group = get_group(conn, group_id)
    if not 1 <= months <= group.max_loan_months:
        raise ChamaError(f"loan period must be 1 to {group.max_loan_months} months")

    def check(state: GroupState, _entries):
        if state.active_loans(member_id):
            raise ChamaError("member already has an active loan")
        limit = loan_limit(state, group, member_id)
        if principal > limit:
            raise ChamaError(f"loan limit is {money.fmt(limit)} ({group.loan_multiplier}x savings)")
        if principal > available_cash(state):
            raise ChamaError(f"only {money.fmt(available_cash(state))} is available to lend")
        rate_bp = group.loan_rate_bp
        return {
            "rate_bp": rate_bp,
            "months": months,
            "method": "flat",
            "interest": money.percent_of(principal, rate_bp * months),
        }

    return _append(
        conn, group_id, Kind.LOAN_DISBURSEMENT, principal, by, member_id, approver, memo, external_ref, now=now, check=check
    )


def repay_loan(conn, group_id: int, by: Member, loan_id: int, amount: int, memo: str = "", external_ref: str = "", now=None) -> Entry:
    def check(state: GroupState, _entries):
        loan = state.loans.get(loan_id)
        if loan is None:
            raise ChamaError(f"loan #{loan_id} not found")
        if loan.outstanding == 0:
            raise ChamaError(f"loan #{loan_id} is already cleared")
        if amount > loan.outstanding:
            raise ChamaError(f"repayment is more than the {money.fmt(loan.outstanding)} outstanding")
        return None

    state = project(db.load_entries(conn, group_id))
    loan = state.loans.get(loan_id)
    if loan is None:
        raise ChamaError(f"loan #{loan_id} not found")
    return _append(
        conn, group_id, Kind.LOAN_REPAYMENT, amount, by, loan.member_id, memo=memo, external_ref=external_ref,
        data={"loan": loan_id}, now=now, check=check,
    )


def expense(conn, group_id: int, by: Member, approver: Member | None, amount: int, memo: str, external_ref: str = "", now=None) -> Entry:
    if not memo.strip():
        raise ChamaError("describe the expense")

    def check(state: GroupState, _entries):
        if amount > available_cash(state):
            raise ChamaError(f"only {money.fmt(available_cash(state))} is available")
        return None

    return _append(conn, group_id, Kind.EXPENSE, amount, by, None, approver, memo, external_ref, now=now, check=check)


def welfare_payout(
    conn, group_id: int, by: Member, approver: Member | None, amount: int, memo: str,
    member_id: int | None = None, external_ref: str = "", now=None,
) -> Entry:
    if not memo.strip():
        raise ChamaError("describe the welfare payout")
    if member_id is not None:
        _require_group_member(conn, group_id, member_id)

    def check(state: GroupState, _entries):
        if amount > state.welfare_fund:
            raise ChamaError(f"welfare fund has only {money.fmt(state.welfare_fund)}")
        return None

    return _append(conn, group_id, Kind.WELFARE_PAYOUT, amount, by, member_id, approver, memo, external_ref, now=now, check=check)


def reverse(conn, group_id: int, by: Member, approver: Member | None, seq: int, reason: str, now=None) -> Entry:
    """Cancel an earlier entry. Both entries stay in the ledger for everyone to see."""
    if not reason.strip():
        raise ChamaError("give the reason for the reversal")

    def check(state: GroupState, entries: list[Entry]):
        target = next((e for e in entries if e.seq == seq), None)
        if target is None:
            raise ChamaError(f"entry #{seq} not found")
        if target.kind == Kind.REVERSAL:
            raise ChamaError("a reversal cannot be reversed; record the entry again instead")
        if seq in state.reversed:
            raise ChamaError(f"entry #{seq} is already reversed")
        if target.kind == Kind.LOAN_DISBURSEMENT and state.loans[seq].repayments:
            raise ChamaError("reverse this loan's repayments first")
        return {"reverses": seq}

    # Amount and member mirror the reversed entry so the reversal reads clearly on statements.
    entries = db.load_entries(conn, group_id)
    target = next((e for e in entries if e.seq == seq), None)
    if target is None:
        raise ChamaError(f"entry #{seq} not found")
    return _append(
        conn, group_id, Kind.REVERSAL, target.amount, by, target.member_id, approver, reason, now=now, check=check
    )


def group_state(conn: sqlite3.Connection, group_id: int) -> GroupState:
    return project(db.load_entries(conn, group_id))
