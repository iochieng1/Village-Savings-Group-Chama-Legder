import pytest
from fastapi.testclient import TestClient

from chama.api import create_app
from chama.sms import ConsoleGateway


@pytest.fixture
def gateway():
    return ConsoleGateway()


@pytest.fixture
def api(gateway):
    client = TestClient(create_app(":memory:", gateway=gateway))
    resp = client.post(
        "/groups",
        json={"name": "Umoja", "chair_name": "Achieng", "chair_phone": "0700000001", "chair_pin": "4826"},
    )
    assert resp.status_code == 201
    gid = resp.json()["group"]["id"]
    chair = {"Authorization": f"Bearer {resp.json()['token']}"}
    client.post(f"/groups/{gid}/members", headers=chair, json={"name": "Wanjiru", "phone": "0700000002", "pin": "5937", "role": "treasurer"})
    alice = client.post(f"/groups/{gid}/members", headers=chair, json={"name": "Akinyi", "phone": "0700000003", "pin": "7193", "language": "sw"}).json()
    treasurer = login(client, gid, "0700000002", "5937")
    alice_auth = login(client, gid, "0700000003", "7193")

    class Api:
        pass

    a = Api()
    a.client, a.gid, a.chair, a.treasurer, a.alice, a.alice_id = client, gid, chair, treasurer, alice_auth, alice["id"]
    return a


def login(client, gid, phone, pin):
    resp = client.post(f"/groups/{gid}/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def entry(a, headers, **body):
    return a.client.post(f"/groups/{a.gid}/entries", headers=headers, json=body)


CHAIR_APPROVAL = {"approver_phone": "0700000001", "approver_pin": "4826"}


def test_health_and_index(api):
    assert api.client.get("/health").json()["status"] == "ok"
    assert api.client.get("/").status_code == 200


def test_auth_required_and_scoped(api):
    assert api.client.get(f"/groups/{api.gid}").status_code == 401
    assert api.client.get(f"/groups/{api.gid}", headers={"Authorization": "Bearer nope"}).status_code == 401
    other = api.client.post(
        "/groups", json={"name": "Other", "chair_name": "O", "chair_phone": "0700000009", "chair_pin": "4826"}
    ).json()
    assert api.client.get(f"/groups/{other['group']['id']}", headers=api.alice).status_code == 403
    assert api.client.post(f"/groups/{api.gid}/login", json={"phone": "0700000003", "pin": "0000"}).status_code == 401


def test_record_contribution_sends_receipt(api, gateway):
    resp = entry(api, api.treasurer, kind="contribution", member_id=api.alice_id, amount="1,500", external_ref="sjk123")
    assert resp.status_code == 201
    body = resp.json()
    assert (body["seq"], body["amount"], body["external_ref"]) == (1, 150000, "SJK123")
    assert gateway.outbox[-1][0] == "+254700000003"
    assert "Akiba ya KES 1,500" in gateway.outbox[-1][1]
    assert entry(api, api.treasurer, kind="contribution", member_id=api.alice_id, amount="100", external_ref="SJK123").status_code == 409


@pytest.mark.parametrize(
    "body,status",
    [
        ({"kind": "contribution", "member_id": 3, "amount": "abc"}, 422),
        ({"kind": "contribution", "member_id": 3, "amount": "-5"}, 422),
        ({"kind": "loan_disbursement", "member_id": 3, "amount": "100"}, 409),
        ({"kind": "loan_repayment", "amount": "100"}, 409),
        ({"kind": "expense", "amount": "100", "memo": "Tea"}, 403),
    ],
)
def test_entry_validation(api, body, status):
    assert entry(api, api.treasurer, **body).status_code == status


def test_members_cannot_record(api):
    assert entry(api, api.alice, kind="contribution", member_id=api.alice_id, amount="100").status_code == 403


def test_loan_flow_with_second_official(api):
    entry(api, api.treasurer, kind="contribution", member_id=api.alice_id, amount="1000")
    bad = entry(api, api.treasurer, kind="loan_disbursement", member_id=api.alice_id, amount="1000", months=2,
                approver_phone="0700000001", approver_pin="9999")
    assert bad.status_code == 401
    loan = entry(api, api.treasurer, kind="loan_disbursement", member_id=api.alice_id, amount="1000", months=2, **CHAIR_APPROVAL)
    assert loan.status_code == 201, loan.text
    assert loan.json()["data"]["interest"] == 20000
    repay = entry(api, api.treasurer, kind="loan_repayment", loan_id=loan.json()["seq"], amount="600")
    assert repay.json()["member_id"] == api.alice_id

    statement = api.client.get(f"/groups/{api.gid}/statements/{api.alice_id}", headers=api.alice).json()
    assert statement["savings"] == 100000
    assert statement["loan_balance"] == 60000
    assert statement["pending_acknowledgement"] == [1, 2, 3]


def test_ledger_ack_dispute_and_reverse(api):
    wrong = entry(api, api.treasurer, kind="contribution", member_id=api.alice_id, amount="5000").json()
    dispute = api.client.post(
        f"/groups/{api.gid}/entries/{wrong['seq']}/acknowledge", headers=api.alice,
        json={"status": "disputed", "note": "I paid 500"},
    )
    assert dispute.status_code == 200
    assert len(api.client.get(f"/groups/{api.gid}/disputes", headers=api.chair).json()) == 1

    assert api.client.post(f"/groups/{api.gid}/entries/1/reverse", headers=api.treasurer, json={"reason": "x"}).status_code == 403
    rev = api.client.post(f"/groups/{api.gid}/entries/1/reverse", headers=api.treasurer, json={"reason": "Was 500", **CHAIR_APPROVAL})
    assert rev.status_code == 201
    assert api.client.get(f"/groups/{api.gid}/disputes", headers=api.chair).json() == []

    ledger = api.client.get(f"/groups/{api.gid}/ledger", params={"lang": "sw"}, headers=api.alice).json()
    assert [e["label"] for e in ledger] == ["Akiba", "Marekebisho (kufuta)"]
    assert ledger[0]["reversed"] is True
    assert ledger[0]["acknowledgement"]["status"] == "disputed"
    assert ledger[1]["approved_by_name"] == "Achieng"


def test_overview_meeting_verify_export(api, gateway):
    entry(api, api.treasurer, kind="contribution", member_id=api.alice_id, amount="1000")
    meeting = api.client.post(f"/groups/{api.gid}/meetings/close", headers=api.treasurer, json={"counted_cash": "900"})
    assert meeting.status_code == 201
    assert meeting.json()["cash_difference"] == -10000
    assert "ZIMEPUNGUA" in dict(gateway.outbox)["+254700000003"]
    assert api.client.post(f"/groups/{api.gid}/meetings/close", headers=api.alice, json={}).status_code == 403

    overview = api.client.get(f"/groups/{api.gid}", headers=api.alice).json()
    assert overview["verification"]["ok"] is True
    assert overview["verification"]["checkpoints_matched"] == 1
    assert overview["summary"]["total_savings"] == 100000
    assert len(api.client.get(f"/groups/{api.gid}/meetings", headers=api.alice).json()) == 1
    assert api.client.get(f"/groups/{api.gid}/verify", headers=api.alice).json()["ok"]
    assert len(api.client.get(f"/groups/{api.gid}/export", headers=api.alice).json()["entries"]) == 1


def test_members_view_masks_phones_for_ordinary_members(api):
    as_member = api.client.get(f"/groups/{api.gid}/members", headers=api.alice).json()
    assert as_member[0]["phone"] == "+254700***001"
    assert as_member[2]["phone"] == "+254700000003"  # own number
    as_official = api.client.get(f"/groups/{api.gid}/members", headers=api.chair).json()
    assert as_official[0]["phone"] == "+254700000001"


def test_share_out_endpoints(api):
    entry(api, api.treasurer, kind="contribution", member_id=api.alice_id, amount="1000")
    entry(api, api.treasurer, kind="fine", member_id=api.alice_id, amount="50", memo="Late")
    plan = api.client.get(f"/groups/{api.gid}/share-out", headers=api.alice).json()
    assert plan["total_payout"] == 105000
    assert api.client.post(f"/groups/{api.gid}/share-out", headers=api.treasurer, json={}).status_code == 403
    done = api.client.post(f"/groups/{api.gid}/share-out", headers=api.treasurer, json=CHAIR_APPROVAL)
    assert done.json() == {"entries": [3]}


def test_logout_and_pin_reset(api):
    assert api.client.post(f"/groups/{api.gid}/logout", headers=api.alice).status_code == 204
    assert api.client.get(f"/groups/{api.gid}", headers=api.alice).status_code == 401
    assert api.client.post(f"/groups/{api.gid}/members/{api.alice_id}/reset-pin", headers=api.chair, json={"new_pin": "1111"}).status_code == 422
    assert api.client.post(f"/groups/{api.gid}/members/{api.alice_id}/reset-pin", headers=api.chair, json={"new_pin": "8642"}).status_code == 204
    login(api.client, api.gid, "0700000003", "8642")


def test_ussd_callback(api):
    form = {"sessionId": "s1", "serviceCode": "*384#", "phoneNumber": "+254700000003", "text": ""}
    resp = api.client.post("/ussd", data=form)
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "CON Umoja\nWeka PIN yako:"
    form["phoneNumber"] = "bad"
    assert api.client.post("/ussd", data=form).text.startswith("END")
