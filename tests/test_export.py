import json

import pytest

from chama import cli, db, export, ledger, meetings, service
from chama.sms import ConsoleGateway

from .helpers import KES, seeded_group


@pytest.fixture
def c(tmp_path):
    path = tmp_path / "chama.db"
    ctx = seeded_group(db.connect(path))
    ctx.path = str(path)
    service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.alice.id, 1000 * KES)
    service.contribute(ctx.conn, ctx.group.id, ctx.treasurer, ctx.bob.id, 500 * KES)
    ctx.meeting = meetings.close_meeting(ctx.conn, ctx.group.id, ctx.chair, ConsoleGateway())
    service.fine(ctx.conn, ctx.group.id, ctx.treasurer, ctx.bob.id, 50 * KES, "Late")
    return ctx


def test_export_contains_no_secrets(c):
    data = export.export_group(c.conn, c.group.id)
    text = json.dumps(data)
    assert "pbkdf2" not in text and "pin" not in text.lower()
    assert data["members"][2]["phone"] == "+254700***003"
    assert data["head"]["seq"] == 3
    assert len(data["entries"]) == 3 and len(data["checkpoints"]) == 1


def test_verify_export_ok_with_sms_fingerprint(c):
    data = export.export_group(c.conn, c.group.id)
    report = export.verify_export(data, c.meeting.fingerprint.lower(), at_seq=c.meeting.seq)
    assert report["ok"]
    assert report["sms_check"]["ok"]
    assert report["summary"]["total_savings"] == 1500 * KES


def test_verify_export_detects_forgery_against_sms(c):
    data = export.export_group(c.conn, c.group.id)
    # Forger rewrites entry 1, re-seals the chain AND rewrites the checkpoints in the file.
    prev, forged = ledger.GENESIS_HASH, []
    for e in data["entries"]:
        entry = ledger.Entry(**{**e, "prev_hash": prev, "amount": 1 * KES if e["seq"] == 1 else e["amount"]})
        entry = ledger.seal(entry)
        forged.append(entry)
        prev = entry.hash
    data["entries"] = [e.__dict__ for e in forged]
    data["checkpoints"] = [{"seq": 2, "hash": forged[1].hash, "closed_at": ""}]
    assert export.verify_export(data)["ok"]  # self-consistent file...
    report = export.verify_export(data, c.meeting.fingerprint, at_seq=2)
    assert not report["ok"]  # ...but not what members were told
    assert report["sms_check"]["found"] != c.meeting.fingerprint


def test_verify_rejects_bad_files():
    with pytest.raises(export.InvalidExport):
        export.verify_export({"format": "other"})
    with pytest.raises(export.InvalidExport):
        export.verify_export({"format": export.FORMAT, "entries": [{"seq": 1}], "checkpoints": []})


def test_cli_export_and_verify(c, tmp_path, capsys):
    out = tmp_path / "ledger.json"
    assert cli.main(["export", "--database", c.path, "--group", str(c.group.id), "-o", str(out)]) == 0
    assert cli.main(["verify", str(out), "--fingerprint", c.meeting.fingerprint, "--at", str(c.meeting.seq)]) == 0
    printed = capsys.readouterr().out
    assert "OK: 3 entries verified" in printed and "matches" in printed

    data = json.loads(out.read_text())
    data["entries"][0]["amount"] = 1
    out.write_text(json.dumps(data))
    assert cli.main(["verify", str(out)]) == 1
    assert "TAMPERED: entry #1" in capsys.readouterr().out

    assert cli.main(["verify", str(tmp_path / "missing.json")]) == 2
    with pytest.raises(SystemExit):
        cli.main(["verify", str(out), "--fingerprint", "ABCD-EF01"])


def test_demo_seed_is_consistent(tmp_path, capsys):
    path = str(tmp_path / "demo.db")
    assert cli.main(["demo", "--database", path]) == 0
    assert "PIN 7193" in capsys.readouterr().out
    conn = db.connect(path)
    check = meetings.verify_group(conn, 1)
    assert check.ok and check.checkpoints_matched == 3
    state = service.group_state(conn, 1)
    assert state.loans_outstanding == 4000 * 100 + 1200 * 100 - 3000 * 100
    assert state.reversed
