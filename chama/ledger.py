"""The tamper-evident ledger.

Every entry stores the hash of the entry before it, and its own hash covers all
of its fields plus that previous hash. Editing, deleting or reordering any past
entry therefore changes every hash after it. At each meeting the latest hash is
sent to every member as a short "fingerprint"; if the records are later altered,
the fingerprints members hold no longer match and anyone can see where the
chain breaks.

Mistakes are never edited away: a REVERSAL entry cancels an earlier entry and
both stay visible.

This module is pure (no database) so the same code verifies the live ledger and
an exported copy on a member's own machine.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import StrEnum

GENESIS_HASH = "0" * 64


class Kind(StrEnum):
    CONTRIBUTION = "contribution"
    FINE = "fine"
    WELFARE_CONTRIBUTION = "welfare_contribution"
    LOAN_DISBURSEMENT = "loan_disbursement"
    LOAN_REPAYMENT = "loan_repayment"
    EXPENSE = "expense"
    WELFARE_PAYOUT = "welfare_payout"
    SHARE_OUT = "share_out"
    REVERSAL = "reversal"


MONEY_IN = frozenset({Kind.CONTRIBUTION, Kind.FINE, Kind.WELFARE_CONTRIBUTION, Kind.LOAN_REPAYMENT})
MONEY_OUT = frozenset({Kind.LOAN_DISBURSEMENT, Kind.EXPENSE, Kind.WELFARE_PAYOUT, Kind.SHARE_OUT})
# Kinds that are always about one member.
MEMBER_KINDS = frozenset(
    {
        Kind.CONTRIBUTION,
        Kind.FINE,
        Kind.WELFARE_CONTRIBUTION,
        Kind.LOAN_DISBURSEMENT,
        Kind.LOAN_REPAYMENT,
        Kind.SHARE_OUT,
    }
)


@dataclass(frozen=True)
class Entry:
    seq: int
    group_id: int
    kind: str
    amount: int  # cents, always positive; direction comes from kind
    member_id: int | None
    recorded_by: int
    approved_by: int | None
    recorded_at: str  # ISO 8601, UTC
    memo: str = ""
    external_ref: str = ""  # e.g. M-Pesa receipt code
    data: dict = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    hash: str = ""

    def hashed_fields(self) -> dict:
        fields = asdict(self)
        fields.pop("hash")
        return fields


def canonical(fields: dict) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def compute_hash(entry: Entry) -> str:
    return hashlib.sha256(canonical(entry.hashed_fields())).hexdigest()


def seal(entry: Entry) -> Entry:
    """Return the entry with its hash filled in."""
    return Entry(**{**entry.hashed_fields(), "hash": compute_hash(entry)})


def fingerprint(hash_hex: str) -> str:
    """Short form that is easy to read out at a meeting or compare in an SMS."""
    head = hash_hex[:8].upper()
    return f"{head[:4]}-{head[4:]}"


@dataclass(frozen=True)
class Checkpoint:
    seq: int
    hash: str
    closed_at: str = ""


@dataclass
class Verification:
    ok: bool
    entries_checked: int
    head_seq: int
    head_hash: str
    broken_at: int | None = None
    reason: str = ""
    checkpoints_matched: int = 0

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.head_hash)


def verify(entries: Iterable[Entry], checkpoints: Iterable[Checkpoint] = ()) -> Verification:
    """Recompute the chain and compare it with every published checkpoint."""
    prev_hash, expected_seq, count = GENESIS_HASH, 1, 0
    hashes: dict[int, str] = {0: GENESIS_HASH}

    def fail(seq: int, reason: str) -> Verification:
        return Verification(False, count, expected_seq - 1, prev_hash, broken_at=seq, reason=reason)

    for entry in entries:
        if entry.seq != expected_seq:
            return fail(entry.seq, f"expected entry #{expected_seq}, found #{entry.seq} (missing or reordered entries)")
        if entry.prev_hash != prev_hash:
            return fail(entry.seq, "does not link to the previous entry")
        if compute_hash(entry) != entry.hash:
            return fail(entry.seq, "contents were changed after it was recorded")
        hashes[entry.seq] = entry.hash
        prev_hash, expected_seq, count = entry.hash, expected_seq + 1, count + 1

    # Every checkpoint is checked, including several at the same entry
    # (meetings with nothing recorded in between).
    matched = 0
    for checkpoint in sorted(checkpoints, key=lambda c: c.seq):
        if checkpoint.seq not in hashes:
            return fail(checkpoint.seq, f"meeting fingerprint for entry #{checkpoint.seq} refers to an entry that no longer exists")
        if hashes[checkpoint.seq] != checkpoint.hash:
            return fail(checkpoint.seq, f"does not match the fingerprint {fingerprint(checkpoint.hash)} sent to members")
        matched += 1

    return Verification(True, count, expected_seq - 1, prev_hash, checkpoints_matched=matched)
