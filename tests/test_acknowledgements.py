import pytest

from chama import acknowledgements as acks
from chama import service
from chama.service import ChamaError, PermissionDenied
from chama.sms import ConsoleGateway

from .helpers import KES, seeded_group


@pytest.fixture
def c():
    ctx = seeded_group()
    ctx.e1 = service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.alice.id, 1000 * KES)
    ctx.e2 = service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.alice.id, 5000 * KES)
    ctx.e3 = service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.bob.id, 500 * KES)
    return ctx


def test_confirm_and_dispute(c):
    assert acks.pending(c.conn, c.group.id, c.alice.id) == [1, 2]
    acks.acknowledge(c.conn, c.group.id, c.alice, 1, acks.CONFIRMED)
    dispute = acks.acknowledge(c.conn, c.group.id, c.alice, 2, acks.DISPUTED, "I paid 500, not 5,000")
    assert dispute.member_name == "Akinyi"
    assert acks.pending(c.conn, c.group.id, c.alice.id) == []
    assert [d.seq for d in acks.open_disputes(c.conn, c.group.id)] == [2]

    # Officials correct it; the dispute closes because the entry is reversed.
    service.reverse(c.conn, c.group.id, c.treasurer, c.chair, 2, "Disputed by member: was KES 500")
    assert acks.open_disputes(c.conn, c.group.id) == []


def test_member_can_change_their_mind(c):
    acks.acknowledge(c.conn, c.group.id, c.alice, 1, acks.DISPUTED, "Not sure")
    acks.acknowledge(c.conn, c.group.id, c.alice, 1, acks.CONFIRMED)
    assert acks.for_group(c.conn, c.group.id)[1].status == "confirmed"


def test_rules(c):
    with pytest.raises(PermissionDenied, match="your name"):
        acks.acknowledge(c.conn, c.group.id, c.bob, 1, acks.CONFIRMED)
    with pytest.raises(ChamaError, match="explain"):
        acks.acknowledge(c.conn, c.group.id, c.alice, 1, acks.DISPUTED)
    with pytest.raises(ChamaError, match="status"):
        acks.acknowledge(c.conn, c.group.id, c.alice, 1, "maybe")
    with pytest.raises(ChamaError, match="not found"):
        acks.acknowledge(c.conn, c.group.id, c.alice, 99, acks.CONFIRMED)


def test_receipt_in_members_language(c):
    gateway = ConsoleGateway()
    acks.send_receipt(gateway, c.group, c.alice, c.e1)
    acks.send_receipt(gateway, c.group, c.bob, c.e3)
    alice_sms, bob_sms = gateway.outbox[0][1], gateway.outbox[1][1]
    assert alice_sms.startswith("Umoja Women Group: Akiba ya KES 1,000 imerekodiwa kwako kama ingizo #1")
    assert "Savings of KES 500 recorded for you as entry #3" in bob_sms
