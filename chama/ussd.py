"""USSD menu for members on feature phones (Africa's Talking callback format).

The session's inputs arrive joined by ``*`` and are replayed on every request:
``[group choice*]PIN*menu*...``. The group choice is asked only when the phone
number belongs to more than one group.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from . import acknowledgements, db, meetings, money, service
from .dates import entry_date
from .i18n import t
from .service import AuthError, Member
from .statements import member_statement

RECENT_ENTRIES = 3


def con(text: str) -> str:
    return f"CON {text}"


def end(text: str) -> str:
    return f"END {text}"


def _memberships(conn: sqlite3.Connection, phone: str) -> list[Member]:
    rows = conn.execute("SELECT id FROM members WHERE phone = ? AND active = 1 ORDER BY group_id", (phone,)).fetchall()
    return [service.get_member(conn, r["id"]) for r in rows]


def handle(conn: sqlite3.Connection, phone: str, text: str, today: date | None = None) -> str:
    today = today or date.today()
    inputs = [part.strip() for part in text.split("*")] if text else []
    memberships = _memberships(conn, phone)
    if not memberships:
        return end(t("ussd.not_member"))

    if len(memberships) > 1:
        if not inputs:
            names = "\n".join(
                f"{i}. {service.get_group(conn, m.group_id).name}" for i, m in enumerate(memberships, 1)
            )
            return con(f"{t('ussd.pick_group', memberships[0].language)}\n{names}")
        choice = inputs.pop(0)
        if not choice.isdigit() or not 1 <= int(choice) <= len(memberships):
            return end(t("ussd.invalid", memberships[0].language))
        member = memberships[int(choice) - 1]
    else:
        member = memberships[0]

    lang = member.language
    group = service.get_group(conn, member.group_id)
    if not inputs:
        return con(t("ussd.pin", lang, group=group.name))
    try:
        service.authenticate(conn, group.id, phone, inputs.pop(0))
    except AuthError as exc:
        return end(str(exc))
    if not inputs:
        return con(t("ussd.menu", lang))

    choice, rest = inputs[0], inputs[1:]
    if choice == "1":
        return _balance(conn, member, today)
    if choice == "2":
        return _recent(conn, member, today)
    if choice == "3":
        return _confirm(conn, member, rest)
    if choice == "4":
        return _fingerprint(conn, member)
    return end(t("ussd.invalid", lang))


def _balance(conn: sqlite3.Connection, member: Member, today: date) -> str:
    entries = db.load_entries(conn, member.group_id)
    statement = member_statement(entries, member.id, today)
    state = service.group_state(conn, member.group_id)
    limit = service.loan_limit(state, service.get_group(conn, member.group_id), member.id)
    return end(
        t(
            "ussd.balance",
            member.language,
            savings=money.fmt(statement.savings),
            loan=money.fmt(statement.loan_balance),
            arrears=money.fmt(sum(loan.arrears for loan in statement.loans)),
            limit=money.fmt(limit),
        )
    )


def _line(entry, lang: str) -> str:
    return f"#{entry.seq} {t('kind.' + entry.kind, lang)} {money.fmt(entry.amount)}"


def _recent(conn: sqlite3.Connection, member: Member, today: date) -> str:
    mine = [e for e in db.load_entries(conn, member.group_id) if e.member_id == member.id][-RECENT_ENTRIES:]
    if not mine:
        return end(t("ussd.no_entries", member.language))
    return end("\n".join(f"{_line(e, member.language)} {entry_date(e.recorded_at):%d/%m}" for e in reversed(mine)))


def _confirm(conn: sqlite3.Connection, member: Member, rest: list[str]) -> str:
    lang = member.language
    pending = acknowledgements.pending(conn, member.group_id, member.id)
    if not pending:
        return end(t("ussd.nothing_pending", lang))
    seq = pending[0]
    if not rest:
        entry = next(e for e in db.load_entries(conn, member.group_id) if e.seq == seq)
        return con(
            t(
                "ussd.confirm_entry",
                lang,
                seq=seq,
                kind=t(f"kind.{entry.kind}", lang),
                amount=money.fmt(entry.amount),
                date=entry_date(entry.recorded_at).isoformat(),
            )
        )
    if rest[0] == "1":
        acknowledgements.acknowledge(conn, member.group_id, member, seq, acknowledgements.CONFIRMED)
        return end(t("ussd.confirmed", lang, seq=seq, left=len(pending) - 1))
    if rest[0] == "2":
        acknowledgements.acknowledge(conn, member.group_id, member, seq, acknowledgements.DISPUTED, "Disputed via USSD")
        return end(t("ussd.disputed", lang, seq=seq))
    return end(t("ussd.invalid", lang))


def _fingerprint(conn: sqlite3.Connection, member: Member) -> str:
    lang = member.language
    meetings_held = meetings.list_meetings(conn, member.group_id)
    if not meetings_held:
        return end(t("ussd.no_meetings", lang))
    last = meetings_held[-1]
    check = meetings.verify_group(conn, member.group_id)
    status = t("ussd.ok", lang) if check.ok else t("ussd.broken", lang, seq=check.broken_at)
    return end(
        t("ussd.fingerprint", lang, date=last["closed_at"][:10], fingerprint=last["fingerprint"], seq=last["seq"], status=status)
    )
