# Chama Ledger

**Transparent records for village savings groups.** Every contribution, loan and repayment goes into a tamper-evident ledger that every member can check: on a smartphone, on a basic phone through USSD and SMS, or offline from a downloaded copy.

## The problem

Informal savings groups (chamas, table banking groups, VSLAs) hold billions of shillings in trust, and they usually fall apart for the same reason: **members lose trust because of poor records.** Typical failures:

- one person keeps the book, and nobody else can check it
- figures are changed after the meeting, or pages go missing
- loans are given to insiders, with no record of who approved them
- members only learn their balance at the end-of-year share-out, when it is too late to dispute anything
- the cash in the box doesn't match the book, and nobody can say when the gap appeared

## How Chama Ledger restores trust

| Trust problem | What the ledger does |
|---|---|
| Records edited later | Every entry is chained to the previous one with a SHA-256 hash. Changing, deleting or reordering any past entry breaks the chain, and the app shows exactly where. Entries are append-only in the database. |
| "The treasurer rewrote everything" | At each meeting close, every member gets an SMS with the ledger **fingerprint** (e.g. `BC02-5191`). Members keep these on their own phones, so even a fully re-hashed forgery no longer matches what they hold. |
| Mistakes covered up | Mistakes are never edited. A **reversal** entry cancels the wrong one with a reason, and both stay visible to everyone. |
| One person controls the money | Only officials record entries. **Money out** (loans, expenses, welfare payouts, share-out) and every reversal need a **second, different official** with their own PIN. |
| Members find out too late | Members get an **SMS receipt** the moment anything is recorded in their name, and can **confirm or dispute** it on the web or by USSD. Open disputes are visible to the whole group. |
| Cash doesn't match the book | Officials enter the counted cash when they close a meeting. Every member's SMS says whether it balanced or was short, and by how much. |
| Double-recorded M-Pesa payments | An M-Pesa receipt code can only be recorded once. |
| "Trust our server" | Anyone can download the ledger and run `python -m chama verify` on their own machine, checking it against the fingerprint in their SMS. |

## Features

- **Contributions, fines and a ring-fenced welfare fund.** Welfare money can't be lent out.
- **Loans:** flat monthly interest (the group sets the rate), a limit of N × savings, one active loan per member, and a cap at available cash. Repayments go to interest first. Each loan shows its installment, arrears and status (current, in arrears, overdue or cleared).
- **Statements:** every member's statement shows running savings and loan balances, reversals and each entry's fingerprint. Every member can see every statement; that openness is deliberate.
- **Group overview:** savings, expected cash, loans outstanding, interest earned, fines, expenses and profit to share.
- **Meetings:** closing a meeting creates a checkpoint, records the cash count and sends SMS balances and the fingerprint in English or Kiswahili.
- **End-of-cycle share-out:** savings plus profit (interest and fines less expenses), shared in proportion to savings and split to the exact cent.
- **USSD for feature phones:** check balance and loan limit, see recent entries, confirm or dispute entries one by one, and see the last meeting fingerprint with a live ledger check.
- **Web page:** members and officials use the same page, which shows the live verification badge at the top.
- **Security:** PINs are stored as salted PBKDF2 hashes and lock after 5 wrong attempts (the chair resets them). Session tokens are stored only as hashes. Ordinary members see other members' phone numbers masked. Exports never contain PINs.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q

python -m chama demo                    # sample group with 3 months of activity; prints logins
uvicorn chama.main:app --reload         # http://localhost:8000  (API docs at /docs)
```

Log in with group number **1**, for example as the treasurer (`0711000002`, PIN `5937`) or as a member (`0711000003`, PIN `7193`). Without Africa's Talking credentials, SMS messages are printed in the server log.

Docker:

```bash
docker build -t chama-ledger .
docker run -p 8000:8000 -v chama-data:/data chama-ledger
```

## Verifying a ledger yourself

```bash
python -m chama export --group 1 -o ledger.json   # or "Download ledger" in the web page
python -m chama verify ledger.json --fingerprint BC02-5191 --at 4
```

```
OK: 4 entries verified, head #4 BC02-5191
   1 meeting fingerprint(s) match
   your SMS fingerprint BC02-5191 at #4 matches
   savings KES 5,000, cash KES 2,000, loans outstanding KES 3,800
```

If anything was changed, it prints `TAMPERED: entry #N ...` or `MISMATCH: your SMS says ...`. The verifier uses only `chama/ledger.py`, `state.py` and `statements.py`, with no database and no server.

## API

All group endpoints need `Authorization: Bearer <token>` from `/login`. Every member can read everything; ✱ means officials only; ✱✱ means an official plus a second official's `approver_phone` and `approver_pin` in the body.

| Method | Path | Purpose |
|---|---|---|
| POST | `/groups` | Create a group (the creator becomes chair) |
| POST | `/groups/{id}/login` | Phone and PIN → token |
| GET | `/groups/{id}` | Overview, summary and verification status |
| GET / POST ✱ | `/groups/{id}/members` | List members (with savings, loan, limit) / add a member |
| POST ✱ | `/groups/{id}/entries` | Record an entry (`kind`: contribution, fine, welfare_contribution, loan_repayment; ✱✱ loan_disbursement, expense, welfare_payout) |
| POST ✱✱ | `/groups/{id}/entries/{seq}/reverse` | Reverse an entry, with a reason |
| GET | `/groups/{id}/ledger` | Full ledger with fingerprints, names and acknowledgements |
| GET | `/groups/{id}/statements/{member}` | A member's statement |
| POST | `/groups/{id}/entries/{seq}/acknowledge` | Confirm or dispute your own entry |
| GET | `/groups/{id}/disputes` | Open disputes |
| GET | `/groups/{id}/verify` | Verify the chain against all meeting fingerprints |
| GET | `/groups/{id}/export` | Ledger export for offline verification |
| POST ✱ / GET | `/groups/{id}/meetings/close`, `/groups/{id}/meetings` | Close a meeting / list meetings |
| GET / POST ✱✱ | `/groups/{id}/share-out` | Preview / execute the share-out |
| POST | `/ussd` | Africa's Talking USSD callback |

## USSD

```
[Choose group, if the number is in several]
Enter PIN
1. My balance           savings, loan balance, arrears, loan limit
2. My recent entries    last 3 entries in your name
3. Confirm my entries   each pending entry: 1. Correct  2. Wrong (dispute)
4. Meeting fingerprint  last fingerprint, plus a live "ledger check: OK"
```

## Design notes

- **Balances are never stored.** They are always recomputed by replaying the ledger (`state.project`), so any copy of the ledger gives the same numbers.
- **Money is integer cents.** Floats never touch a balance. Pro-rata splits use the largest-remainder method, so shares always add up exactly.
- **Rules run inside the write lock.** Loan limits, available cash and outstanding balances are checked inside the same `BEGIN IMMEDIATE` transaction as the append, so two simultaneous requests can't both spend the last shilling.
- **Limits of tamper evidence:** someone with direct database access can still edit records; the design makes sure they **cannot do it unnoticed**. That is why the fingerprint SMS goes to every member's own phone.

## Roadmap

- M-Pesa C2B/STK integration, so contributions are recorded automatically from the payment
- Reducing-balance interest and loan penalties as group options
- Merry-go-round (rotating payout) groups
- Kiswahili for the web page (SMS and USSD are already bilingual)
- Signed PDF statements

## License

MIT, see [LICENSE](LICENSE).
