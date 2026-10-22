"""Helpers to build sealed ledgers in tests."""

from chama.ledger import GENESIS_HASH, Entry, seal


class ChainBuilder:
    def __init__(self, group_id=1):
        self.group_id = group_id
        self.entries = []

    def add(self, kind, amount, member_id=None, day="2026-01-05", data=None, recorded_by=1, approved_by=None):
        prev = self.entries[-1].hash if self.entries else GENESIS_HASH
        entry = seal(
            Entry(
                seq=len(self.entries) + 1,
                group_id=self.group_id,
                kind=str(kind),
                amount=amount,
                member_id=member_id,
                recorded_by=recorded_by,
                approved_by=approved_by,
                recorded_at=f"{day}T09:00:00+00:00",
                data=data or {},
                prev_hash=prev,
            )
        )
        self.entries.append(entry)
        return entry
