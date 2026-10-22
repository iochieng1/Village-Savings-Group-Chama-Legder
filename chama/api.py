"""HTTP API.

Every member of a group can read everything about the group: the full ledger,
anyone's statement, disputes and verification results. That openness is the
point. Only officials record entries, and money leaving the group needs a
second official's phone and PIN in the same request.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from datetime import date
from importlib import resources
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__, acknowledgements, db, meetings, money, service, sessions, share_out
from .export import export_group
from .i18n import t
from .ledger import Kind, fingerprint
from .phone import InvalidPhone, mask
from .security import WeakPin
from .service import AuthError, ChamaError, Member, PermissionDenied
from .sms import SmsGateway, from_env
from .statements import group_summary, member_statement

Amount = Annotated[str, Field(description='Amount in shillings, e.g. "1500" or "1,500.50"', examples=["1500"])]


class CreateGroup(BaseModel):
    name: str
    chair_name: str
    chair_phone: str
    chair_pin: str
    loan_rate_bp: int = Field(1000, description="Flat interest per month in basis points (1000 = 10%)")
    loan_multiplier: int = 3
    max_loan_months: int = 6


class Login(BaseModel):
    phone: str
    pin: str


class NewMember(BaseModel):
    name: str
    phone: str
    pin: str
    role: Literal["member", "chair", "treasurer", "secretary"] = "member"
    language: Literal["en", "sw"] = "en"


class ResetPin(BaseModel):
    new_pin: str


class Approval(BaseModel):
    approver_phone: str | None = None
    approver_pin: str | None = None


class NewEntry(Approval):
    kind: Literal[
        "contribution",
        "fine",
        "welfare_contribution",
        "loan_disbursement",
        "loan_repayment",
        "expense",
        "welfare_payout",
    ]
    amount: Amount
    member_id: int | None = None
    loan_id: int | None = None
    months: int | None = None
    memo: str = ""
    external_ref: str = Field("", description="M-Pesa or bank receipt code")


class Reversal(Approval):
    reason: str


class Ack(BaseModel):
    status: Literal["confirmed", "disputed"]
    note: str = ""


class CloseMeeting(BaseModel):
    counted_cash: Amount | None = None
    note: str = ""


def get_conn(request: Request) -> sqlite3.Connection:
    return request.app.state.conn


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def current_member(group_id: int, conn: Conn, authorization: Annotated[str | None, Header()] = None) -> Member:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("log in first")
    member = sessions.resolve(conn, authorization[7:].strip())
    if member.group_id != group_id:
        raise PermissionDenied("you are not a member of this group")
    return member


Me = Annotated[Member, Depends(current_member)]


def _approver(conn: sqlite3.Connection, group_id: int, body: Approval) -> Member | None:
    if not body.approver_phone:
        return None
    return service.authenticate(conn, group_id, body.approver_phone, body.approver_pin or "")


def _member_view(m: Member, viewer: Member) -> dict:
    phone = m.phone if viewer.is_official or viewer.id == m.id else mask(m.phone)
    return {"id": m.id, "name": m.name, "phone": phone, "role": m.role, "language": m.language, "active": m.active}


def create_app(database: str | None = None, gateway: SmsGateway | None = None) -> FastAPI:
    app = FastAPI(
        title="Chama Ledger",
        version=__version__,
        description="Tamper-evident records for savings groups: contributions, loans and statements every member can verify.",
    )
    app.state.conn = db.connect(database or os.getenv("CHAMA_DATABASE", "chama.db"))
    sms = gateway or from_env()
    app.state.sms = sms

    errors = {
        AuthError: 401,
        PermissionDenied: 403,
        money.InvalidAmount: 422,
        InvalidPhone: 422,
        WeakPin: 422,
        ChamaError: 409,
    }
    for exc_type, status in errors.items():
        app.add_exception_handler(
            exc_type, lambda request, exc, status=status: JSONResponse({"detail": str(exc)}, status_code=status)
        )

    index_html = resources.files("chama.static").joinpath("index.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        return index_html

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    # Groups and access
    @app.post("/groups", status_code=201)
    def create_group(body: CreateGroup, conn: Conn):
        group, chair = service.create_group(
            conn, body.name, body.chair_name, body.chair_phone, body.chair_pin,
            body.loan_rate_bp, body.loan_multiplier, body.max_loan_months,
        )
        return {"group": asdict(group), "chair": _member_view(chair, chair), "token": sessions.create(conn, chair)}

    @app.post("/groups/{group_id}/login")
    def login(group_id: int, body: Login, conn: Conn):
        member = service.authenticate(conn, group_id, body.phone, body.pin)
        return {"token": sessions.create(conn, member), "member": _member_view(member, member)}

    @app.post("/groups/{group_id}/logout", status_code=204)
    def logout(group_id: int, me: Me, conn: Conn, authorization: Annotated[str, Header()]):
        sessions.revoke(conn, authorization[7:].strip())

    @app.get("/groups/{group_id}")
    def group_overview(group_id: int, me: Me, conn: Conn):
        state = service.group_state(conn, group_id)
        check = meetings.verify_group(conn, group_id)
        return {
            "group": asdict(service.get_group(conn, group_id)),
            "me": _member_view(me, me),
            "summary": asdict(group_summary(state, date.today())),
            "verification": {**asdict(check), "fingerprint": check.fingerprint},
            "open_disputes": len(acknowledgements.open_disputes(conn, group_id)),
        }

    @app.get("/groups/{group_id}/members")
    def members(group_id: int, me: Me, conn: Conn):
        state = service.group_state(conn, group_id)
        group = service.get_group(conn, group_id)
        result = []
        for m in service.list_members(conn, group_id):
            ms = state.members.get(m.id)
            result.append(
                {
                    **_member_view(m, me),
                    "savings": ms.savings if ms else 0,
                    "loan_balance": sum(loan.outstanding for loan in state.active_loans(m.id)),
                    "loan_limit": service.loan_limit(state, group, m.id),
                }
            )
        return result

    @app.post("/groups/{group_id}/members", status_code=201)
    def add_member(group_id: int, body: NewMember, me: Me, conn: Conn):
        member = service.add_member(conn, group_id, me, body.name, body.phone, body.pin, body.role, body.language)
        return _member_view(member, me)

    @app.post("/groups/{group_id}/members/{member_id}/reset-pin", status_code=204)
    def reset_pin(group_id: int, member_id: int, body: ResetPin, me: Me, conn: Conn):
        service.reset_pin(conn, group_id, me, member_id, body.new_pin)

    # Recording
    @app.post("/groups/{group_id}/entries", status_code=201)
    def record(group_id: int, body: NewEntry, me: Me, conn: Conn):
        amount = money.parse(body.amount)
        approver = _approver(conn, group_id, body)
        g, ref, memo = group_id, body.external_ref, body.memo
        kind = Kind(body.kind)
        if kind is Kind.CONTRIBUTION:
            entry = service.contribute(conn, g, me, body.member_id, amount, memo, ref)
        elif kind is Kind.FINE:
            entry = service.fine(conn, g, me, body.member_id, amount, memo, ref)
        elif kind is Kind.WELFARE_CONTRIBUTION:
            entry = service.welfare_contribution(conn, g, me, body.member_id, amount, memo, ref)
        elif kind is Kind.LOAN_DISBURSEMENT:
            if body.months is None:
                raise ChamaError("months is required for a loan")
            entry = service.disburse_loan(conn, g, me, approver, body.member_id, amount, body.months, memo, ref)
        elif kind is Kind.LOAN_REPAYMENT:
            if body.loan_id is None:
                raise ChamaError("loan_id is required for a repayment")
            entry = service.repay_loan(conn, g, me, body.loan_id, amount, memo, ref)
        elif kind is Kind.EXPENSE:
            entry = service.expense(conn, g, me, approver, amount, memo, ref)
        else:
            entry = service.welfare_payout(conn, g, me, approver, amount, memo, body.member_id, ref)
        if entry.member_id is not None:
            acknowledgements.send_receipt(sms, service.get_group(conn, g), service.get_member(conn, entry.member_id), entry)
        return {**asdict(entry), "fingerprint": fingerprint(entry.hash)}

    @app.post("/groups/{group_id}/entries/{seq}/reverse", status_code=201)
    def reverse(group_id: int, seq: int, body: Reversal, me: Me, conn: Conn):
        entry = service.reverse(conn, group_id, me, _approver(conn, group_id, body), seq, body.reason)
        return {**asdict(entry), "fingerprint": fingerprint(entry.hash)}

    # Reading and verifying
    @app.get("/groups/{group_id}/ledger")
    def ledger(group_id: int, me: Me, conn: Conn, lang: Literal["en", "sw"] = "en"):
        names = {m.id: m.name for m in service.list_members(conn, group_id)}
        entries = db.load_entries(conn, group_id)
        state = service.group_state(conn, group_id)
        acks = acknowledgements.for_group(conn, group_id)
        return [
            {
                **asdict(e),
                "label": t(f"kind.{e.kind}", lang),
                "member_name": names.get(e.member_id),
                "recorded_by_name": names.get(e.recorded_by),
                "approved_by_name": names.get(e.approved_by),
                "fingerprint": fingerprint(e.hash),
                "reversed": e.seq in state.reversed,
                "acknowledgement": asdict(acks[e.seq]) if e.seq in acks else None,
            }
            for e in entries
        ]

    @app.get("/groups/{group_id}/statements/{member_id}")
    def statement(group_id: int, member_id: int, me: Me, conn: Conn):
        target = service.get_member(conn, member_id)
        if target.group_id != group_id:
            raise ChamaError("member is not in this group")
        result = member_statement(db.load_entries(conn, group_id), member_id, date.today())
        return {
            "member": _member_view(target, me),
            **asdict(result),
            "loan_balance": result.loan_balance,
            "pending_acknowledgement": acknowledgements.pending(conn, group_id, member_id),
        }

    @app.post("/groups/{group_id}/entries/{seq}/acknowledge")
    def acknowledge(group_id: int, seq: int, body: Ack, me: Me, conn: Conn):
        return asdict(acknowledgements.acknowledge(conn, group_id, me, seq, body.status, body.note))

    @app.get("/groups/{group_id}/disputes")
    def disputes(group_id: int, me: Me, conn: Conn):
        return [asdict(d) for d in acknowledgements.open_disputes(conn, group_id)]

    @app.get("/groups/{group_id}/verify")
    def verify(group_id: int, me: Me, conn: Conn):
        check = meetings.verify_group(conn, group_id)
        return {**asdict(check), "fingerprint": check.fingerprint}

    @app.get("/groups/{group_id}/export")
    def export(group_id: int, me: Me, conn: Conn):
        return export_group(conn, group_id)

    # Meetings and share-out
    @app.post("/groups/{group_id}/meetings/close", status_code=201)
    def close_meeting(group_id: int, body: CloseMeeting, me: Me, conn: Conn):
        counted = money.parse(body.counted_cash) if body.counted_cash not in (None, "") else None
        result = meetings.close_meeting(conn, group_id, me, sms, counted, body.note)
        return {**asdict(result), "cash_difference": result.cash_difference}

    @app.get("/groups/{group_id}/meetings")
    def list_meetings(group_id: int, me: Me, conn: Conn):
        return meetings.list_meetings(conn, group_id)

    @app.get("/groups/{group_id}/share-out")
    def share_out_preview(group_id: int, me: Me, conn: Conn):
        plan = share_out.preview(conn, group_id)
        return {**asdict(plan), "total_payout": plan.total_payout}

    @app.post("/groups/{group_id}/share-out", status_code=201)
    def share_out_execute(group_id: int, body: Approval, me: Me, conn: Conn):
        entries = share_out.execute(conn, group_id, me, _approver(conn, group_id, body))
        return {"entries": [e.seq for e in entries]}

    return app
