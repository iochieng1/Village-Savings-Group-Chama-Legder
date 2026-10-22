from datetime import date

import pytest

from chama import acknowledgements, meetings, service, ussd
from chama.sms import ConsoleGateway

from .helpers import KES, seeded_group

ALICE = "+254700000003"  # Kiswahili
BOB = "+254700000004"  # English


@pytest.fixture
def c():
    ctx = seeded_group()
    service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.bob.id, 1000 * KES)
    service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.bob.id, 5000 * KES)
    service.disburse_loan(ctx.conn, ctx.group.id, ctx.treasurer, ctx.chair, ctx.bob.id, 1000 * KES, 2)
    return ctx


def dial(c, phone, text):
    return ussd.handle(c.conn, phone, text, today=date.today())


def test_unknown_number(c):
    assert dial(c, "+254799999999", "") == "END This number is not registered in any group."


def test_pin_then_menu(c):
    assert dial(c, BOB, "") == "CON Umoja Women Group\nEnter your PIN:"
    assert dial(c, BOB, "2468").startswith("CON 1. My balance")
    assert dial(c, BOB, "0000").startswith("END wrong")
    assert dial(c, ALICE, "7193").startswith("CON 1. Salio langu")
    assert dial(c, BOB, "2468*9").startswith("END Invalid")


def test_balance(c):
    reply = dial(c, BOB, "2468*1")
    assert "Savings: KES 6,000" in reply
    assert "Loan balance: KES 1,200" in reply
    assert "Loan limit: KES 18,000" in reply


def test_recent_entries(c):
    reply = dial(c, BOB, "2468*2")
    assert reply.splitlines()[0].startswith("END #3 Loan issued KES 1,000")
    assert dial(c, ALICE, "7193*2") == "END Hakuna maingizo bado."


def test_confirm_and_dispute_walkthrough(c):
    assert dial(c, BOB, "2468*3").startswith("CON #1 Savings KES 1,000")
    assert dial(c, BOB, "2468*3*1") == "END Confirmed #1. 2 more to check."
    assert dial(c, BOB, "2468*3").startswith("CON #2 Savings KES 5,000")
    assert dial(c, BOB, "2468*3*2").startswith("END Dispute on #2 recorded")
    assert dial(c, BOB, "2468*3*1") == "END Confirmed #3. 0 more to check."
    assert dial(c, BOB, "2468*3") == "END All your entries are confirmed. Thank you."
    [dispute] = acknowledgements.open_disputes(c.conn, c.group.id)
    assert (dispute.seq, dispute.note) == (2, "Disputed via USSD")


def test_fingerprint(c):
    assert dial(c, BOB, "2468*4") == "END No meeting has been closed yet."
    result = meetings.close_meeting(c.conn, c.group.id, c.chair, ConsoleGateway())
    reply = dial(c, ALICE, "7193*4")
    assert result.fingerprint in reply and "#3" in reply and reply.endswith("SAWA")


def test_member_of_two_groups_picks_group(c):
    other, chair = service.create_group(c.conn, "Jirani Chama", "Otieno", "0700000010", "4826")
    service.add_member(c.conn, other.id, chair, "Barasa", BOB, "8642")
    menu = dial(c, BOB, "")
    assert menu == "CON Choose your group:\n1. Umoja Women Group\n2. Jirani Chama"
    assert dial(c, BOB, "2") == "CON Jirani Chama\nEnter your PIN:"
    assert "Savings: KES 0" in dial(c, BOB, "2*8642*1")
    assert dial(c, BOB, "3").startswith("END Invalid")


def test_screens_fit_ussd_limit(c):
    for text in ["", "2468", "2468*1", "2468*2", "2468*3", "2468*4"]:
        assert len(dial(c, BOB, text)) <= 182, text
    for text in ["", "7193", "7193*1"]:
        assert len(dial(c, ALICE, text)) <= 182, text
