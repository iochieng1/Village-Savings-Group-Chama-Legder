"""A small seeded group used by service-level tests."""

from types import SimpleNamespace

from chama import db, service

KES = 100


def seeded_group(conn=None):
    conn = conn or db.connect()
    group, chair = service.create_group(conn, "Umoja Women Group", "Achieng", "0700000001", "4826")
    treasurer = service.add_member(conn, group.id, chair, "Wanjiru", "0700000002", "5937", role="treasurer")
    alice = service.add_member(conn, group.id, chair, "Akinyi", "0700000003", "7193", language="sw")
    bob = service.add_member(conn, group.id, treasurer, "Barasa", "0700000004", "2468")
    return SimpleNamespace(conn=conn, group=group, chair=chair, treasurer=treasurer, alice=alice, bob=bob)
