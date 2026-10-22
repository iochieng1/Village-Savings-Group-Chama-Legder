"""Login sessions: random bearer tokens, stored only as SHA-256 hashes."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta

from .dates import utc_now
from .service import AuthError, Member, get_member

SESSION_HOURS = 8


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(conn: sqlite3.Connection, member: Member, now: datetime | None = None) -> str:
    now = now or utc_now()
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
    conn.execute(
        "INSERT INTO sessions (token_hash, member_id, expires_at) VALUES (?, ?, ?)",
        (_digest(token), member.id, (now + timedelta(hours=SESSION_HOURS)).isoformat()),
    )
    return token


def resolve(conn: sqlite3.Connection, token: str, now: datetime | None = None) -> Member:
    row = conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (_digest(token),)).fetchone()
    if row is None or row["expires_at"] < (now or utc_now()).isoformat():
        raise AuthError("session expired; log in again")
    member = get_member(conn, row["member_id"])
    if not member.active:
        raise AuthError("account is inactive")
    return member


def revoke(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))
