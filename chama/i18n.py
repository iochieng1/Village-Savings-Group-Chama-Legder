"""English and Kiswahili messages."""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "kind.contribution": {"en": "Savings", "sw": "Akiba"},
    "kind.fine": {"en": "Fine", "sw": "Faini"},
    "kind.welfare_contribution": {"en": "Welfare contribution", "sw": "Mchango wa ustawi"},
    "kind.loan_disbursement": {"en": "Loan issued", "sw": "Mkopo uliotolewa"},
    "kind.loan_repayment": {"en": "Loan repayment", "sw": "Malipo ya mkopo"},
    "kind.expense": {"en": "Group expense", "sw": "Matumizi ya kikundi"},
    "kind.welfare_payout": {"en": "Welfare payout", "sw": "Malipo ya ustawi"},
    "kind.share_out": {"en": "Share-out", "sw": "Mgao"},
    "kind.reversal": {"en": "Correction (reversal)", "sw": "Marekebisho (kufuta)"},
    "sms.entry_recorded": {
        "en": "{group}: {kind} of {amount} recorded for you as entry #{seq} ({fingerprint}). If this is wrong, dispute it in the app or USSD.",
        "sw": "{group}: {kind} ya {amount} imerekodiwa kwako kama ingizo #{seq} ({fingerprint}). Kama si sahihi, ipinge kwenye programu au USSD.",
    },
    "sms.meeting_closed": {
        "en": "{group} meeting closed. Your savings: {savings}. Loan balance: {loan}. Ledger fingerprint {fingerprint} at entry #{seq}. Keep this SMS as proof.{cash}",
        "sw": "Mkutano wa {group} umefungwa. Akiba yako: {savings}. Deni la mkopo: {loan}. Alama ya leja {fingerprint} kwenye ingizo #{seq}. Hifadhi SMS hii kama ushahidi.{cash}",
    },
    "cash.balanced": {"en": " Cash count balanced.", "sw": " Hesabu ya pesa imelingana."},
    "cash.short": {"en": " Cash count SHORT by {amount}.", "sw": " Pesa ZIMEPUNGUA kwa {amount}."},
    "cash.over": {"en": " Cash count over by {amount}.", "sw": " Pesa zimezidi kwa {amount}."},
}


def t(key: str, lang: str = "en", **params) -> str:
    entry = MESSAGES[key]
    text = entry.get(lang) or entry["en"]
    return text.format(**params) if params else text
