from datetime import datetime, timedelta, timezone

import pytest

from chama import sessions
from chama.service import AuthError

from .helpers import seeded_group

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)


def test_session_lifecycle():
    c = seeded_group()
    token = sessions.create(c.conn, c.alice, now=NOW)
    assert sessions.resolve(c.conn, token, now=NOW + timedelta(hours=7)).id == c.alice.id
    with pytest.raises(AuthError, match="expired"):
        sessions.resolve(c.conn, token, now=NOW + timedelta(hours=9))
    stored = c.conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert token not in stored
    sessions.revoke(c.conn, token)
    with pytest.raises(AuthError):
        sessions.resolve(c.conn, token, now=NOW)


def test_inactive_member_session_rejected():
    c = seeded_group()
    token = sessions.create(c.conn, c.bob, now=NOW)
    c.conn.execute("UPDATE members SET active = 0 WHERE id = ?", (c.bob.id,))
    with pytest.raises(AuthError, match="inactive"):
        sessions.resolve(c.conn, token, now=NOW)
