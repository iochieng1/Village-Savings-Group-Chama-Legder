"""Seed a sample group for trying the app (never use these PINs for real)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import meetings, service
from .sms import ConsoleGateway

KES = 100
MEMBERS = [
    # name, phone, pin, role, language
    ("Achieng Otieno", "0711000001", "4826", "chair", "en"),
    ("Wanjiru Kamau", "0711000002", "5937", "treasurer", "en"),
    ("Akinyi Odhiambo", "0711000003", "7193", "member", "sw"),
    ("Barasa Wekesa", "0711000004", "2468", "member", "en"),
    ("Chebet Kiprono", "0711000005", "3691", "member", "sw"),
]


def seed(conn: sqlite3.Connection) -> int:
    """Create the demo group with three months of activity. Returns the group id."""
    start = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=90)
    name, phone, pin, _, _ = MEMBERS[0]
    group, chair = service.create_group(conn, "Umoja Women Group (demo)", name, phone, pin)
    people = {"chair": chair}
    for name, phone, pin, role, lang in MEMBERS[1:]:
        people[name.split()[0]] = service.add_member(conn, group.id, chair, name, phone, pin, role, lang)
    treasurer = people["Wanjiru"]
    savers = [chair, treasurer, people["Akinyi"], people["Barasa"], people["Chebet"]]
    quiet = ConsoleGateway()  # demo SMS are not printed

    for month in range(3):
        day = start + timedelta(days=30 * month)
        for i, member in enumerate(savers):
            service.contribute(conn, group.id, treasurer, member.id, (1000 + 500 * i) * KES,
                               external_ref=f"DEMO{month}{i}", now=day)
            service.welfare_contribution(conn, group.id, treasurer, member.id, 100 * KES, now=day)
        if month == 0:
            loan = service.disburse_loan(conn, group.id, treasurer, chair, people["Akinyi"].id, 4000 * KES, 3,
                                         memo="School fees", now=day)
        else:
            service.repay_loan(conn, group.id, treasurer, loan.seq, 1500 * KES, now=day)
        if month == 1:
            service.fine(conn, group.id, treasurer, people["Barasa"].id, 50 * KES, "Late for meeting", now=day)
            wrong = service.contribute(conn, group.id, treasurer, people["Chebet"].id, 25000 * KES, now=day)
            service.reverse(conn, group.id, treasurer, chair, wrong.seq, "Typo: KES 250 entered as 25,000", now=day)
            service.contribute(conn, group.id, treasurer, people["Chebet"].id, 250 * KES, now=day)
        if month == 2:
            service.expense(conn, group.id, treasurer, chair, 300 * KES, "Hall hire", now=day)
        meetings.close_meeting(conn, group.id, treasurer, quiet, now=day + timedelta(hours=2))
    return group.id
