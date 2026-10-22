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
    # USSD screens (keep each under ~160 characters)
    "ussd.pick_group": {"en": "Choose your group:", "sw": "Chagua kikundi chako:"},
    "ussd.pin": {"en": "{group}\nEnter your PIN:", "sw": "{group}\nWeka PIN yako:"},
    "ussd.menu": {
        "en": "1. My balance\n2. My recent entries\n3. Confirm my entries\n4. Meeting fingerprint",
        "sw": "1. Salio langu\n2. Maingizo yangu ya karibuni\n3. Thibitisha maingizo yangu\n4. Alama ya mkutano",
    },
    "ussd.balance": {
        "en": "Savings: {savings}\nLoan balance: {loan}\nArrears: {arrears}\nLoan limit: {limit}",
        "sw": "Akiba: {savings}\nDeni la mkopo: {loan}\nMalimbikizo: {arrears}\nKikomo cha mkopo: {limit}",
    },
    "ussd.no_entries": {"en": "No entries yet.", "sw": "Hakuna maingizo bado."},
    "ussd.nothing_pending": {"en": "All your entries are confirmed. Thank you.", "sw": "Maingizo yako yote yamethibitishwa. Asante."},
    "ussd.confirm_entry": {
        "en": "#{seq} {kind} {amount} on {date}. Is this correct?\n1. Yes\n2. No, dispute it",
        "sw": "#{seq} {kind} {amount} tarehe {date}. Ni sahihi?\n1. Ndiyo\n2. Hapana, ipinge",
    },
    "ussd.confirmed": {"en": "Confirmed #{seq}. {left} more to check.", "sw": "Umethibitisha #{seq}. Zimebaki {left} za kuangalia."},
    "ussd.disputed": {
        "en": "Dispute on #{seq} recorded. The whole group can see it until officials correct it.",
        "sw": "Pingamizi kwa #{seq} limerekodiwa. Kikundi kizima kinaliona hadi viongozi warekebishe.",
    },
    "ussd.fingerprint": {
        "en": "Last meeting {date}: fingerprint {fingerprint} at entry #{seq}. Ledger check: {status}",
        "sw": "Mkutano wa mwisho {date}: alama {fingerprint} kwenye ingizo #{seq}. Ukaguzi wa leja: {status}",
    },
    "ussd.no_meetings": {"en": "No meeting has been closed yet.", "sw": "Hakuna mkutano uliofungwa bado."},
    "ussd.ok": {"en": "OK", "sw": "SAWA"},
    "ussd.broken": {"en": "FAILED at entry #{seq}. Raise it with the group.", "sw": "IMESHINDWA kwenye ingizo #{seq}. Lieleze kwa kikundi."},
    "ussd.not_member": {"en": "This number is not registered in any group.", "sw": "Nambari hii haijasajiliwa kwenye kikundi chochote."},
    "ussd.invalid": {"en": "Invalid input. Please dial again.", "sw": "Ingizo si sahihi. Tafadhali piga tena."},
}


def t(key: str, lang: str = "en", **params) -> str:
    entry = MESSAGES[key]
    text = entry.get(lang) or entry["en"]
    return text.format(**params) if params else text
