from dataclasses import replace

import pytest

from chama.ledger import GENESIS_HASH, Checkpoint, Entry, Kind, compute_hash, fingerprint, seal, verify


def build_chain(n=4):
    entries, prev = [], GENESIS_HASH
    for seq in range(1, n + 1):
        entry = seal(
            Entry(
                seq=seq,
                group_id=1,
                kind=Kind.CONTRIBUTION,
                amount=50000,
                member_id=seq,
                recorded_by=1,
                approved_by=None,
                recorded_at=f"2026-10-0{seq}T10:00:00+00:00",
                memo="Monthly saving",
                prev_hash=prev,
            )
        )
        entries.append(entry)
        prev = entry.hash
    return entries


def test_seal_is_deterministic():
    a, b = build_chain(1)[0], build_chain(1)[0]
    assert a.hash == b.hash == compute_hash(a)
    assert len(a.hash) == 64


def test_hash_covers_unicode_and_data():
    entry = build_chain(1)[0]
    changed = seal(replace(entry, memo="Akiba ya mwezi — Oktoba", data={"loan": 3}))
    assert changed.hash != entry.hash


def test_fingerprint_format():
    assert fingerprint("abcdef0123" + "0" * 54) == "ABCD-EF01"


def test_valid_chain_verifies():
    chain = build_chain()
    result = verify(chain, [Checkpoint(2, chain[1].hash), Checkpoint(4, chain[3].hash)])
    assert result.ok
    assert result.entries_checked == 4
    assert result.head_seq == 4
    assert result.head_hash == chain[-1].hash
    assert result.checkpoints_matched == 2
    assert result.fingerprint == fingerprint(chain[-1].hash)


def test_empty_ledger_verifies():
    result = verify([], [Checkpoint(0, GENESIS_HASH)])
    assert result.ok and result.head_seq == 0 and result.checkpoints_matched == 1


def test_edited_amount_detected():
    chain = build_chain()
    chain[1] = replace(chain[1], amount=5000)  # quietly reduced, hash left alone
    result = verify(chain)
    assert not result.ok
    assert result.broken_at == 2
    assert "changed" in result.reason


def test_rehashed_edit_breaks_the_link():
    chain = build_chain()
    chain[1] = seal(replace(chain[1], amount=5000))  # forger recomputes this hash only
    result = verify(chain)
    assert result.broken_at == 3
    assert "previous entry" in result.reason


def test_fully_rewritten_chain_caught_by_checkpoint():
    chain = build_chain()
    published = Checkpoint(4, chain[3].hash)
    # Forger edits entry 2 and re-seals everything after it.
    forged, prev = chain[:1], chain[0].hash
    for entry in chain[1:]:
        new = seal(replace(entry, amount=1000 if entry.seq == 2 else entry.amount, prev_hash=prev))
        forged.append(new)
        prev = new.hash
    assert verify(forged).ok  # internally consistent...
    result = verify(forged, [published])
    assert not result.ok  # ...but members' fingerprints expose it
    assert result.broken_at == 4
    assert fingerprint(published.hash) in result.reason


@pytest.mark.parametrize("mutate,reason", [(lambda c: c.pop(1), "missing"), (lambda c: c.reverse(), "missing")])
def test_deleted_or_reordered_entries(mutate, reason):
    chain = build_chain()
    mutate(chain)
    result = verify(chain)
    assert not result.ok
    assert reason in result.reason


def test_truncated_ledger_caught_by_checkpoint():
    chain = build_chain()
    result = verify(chain[:2], [Checkpoint(4, chain[3].hash)])
    assert not result.ok
    assert "no longer exists" in result.reason
