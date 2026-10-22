"""Kenyan mobile number normalisation (E.164, +254...)."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"^(?:\+?254|0)?([17]\d{8})$")


class InvalidPhone(ValueError):
    pass


def normalise(raw: str) -> str:
    digits = re.sub(r"[\s\-()]", "", raw or "")
    match = _PATTERN.match(digits)
    if not match:
        raise InvalidPhone(f"not a Kenyan mobile number: {raw!r}")
    return "+254" + match.group(1)


def mask(phone: str) -> str:
    return phone[:7] + "***" + phone[-3:] if len(phone) > 10 else "***"
