"""Money as integer cents. Floats never touch a balance."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCY = "KES"
_AMOUNT = re.compile(r"^\d{1,3}(,\d{3})*(\.\d{1,2})?$|^\d+(\.\d{1,2})?$")


class InvalidAmount(ValueError):
    pass


def parse(raw: str | int, allow_zero: bool = False) -> int:
    """Parse a shilling amount such as "1,500" or "250.50" into cents.

    Amounts must be positive unless ``allow_zero`` is set (e.g. a cash count).
    """
    minimum = 0 if allow_zero else 1
    if isinstance(raw, int):
        if raw * 100 < minimum:
            raise InvalidAmount("amount must be positive")
        return raw * 100
    text = str(raw).strip().upper().removeprefix(CURRENCY).strip()
    if not _AMOUNT.match(text):
        raise InvalidAmount(f"not a valid amount: {raw!r}")
    try:
        cents = int(Decimal(text.replace(",", "")) * 100)
    except InvalidOperation as exc:
        raise InvalidAmount(f"not a valid amount: {raw!r}") from exc
    if cents < minimum:
        raise InvalidAmount("amount must be positive")
    return cents


def fmt(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    shillings, rem = divmod(abs(cents), 100)
    text = f"{shillings:,}" if rem == 0 else f"{shillings:,}.{rem:02d}"
    return f"{sign}{CURRENCY} {text}"


def percent_of(cents: int, basis_points: int) -> int:
    """cents * basis_points / 10000, rounded half-up to the nearest cent."""
    value = Decimal(cents) * Decimal(basis_points) / Decimal(10_000)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def split_pro_rata(total: int, weights: dict) -> dict:
    """Split ``total`` cents in proportion to ``weights`` so the parts add up exactly.

    Uses the largest-remainder method: everyone gets the floor of their share,
    then leftover cents go to the largest fractional remainders.
    """
    weight_sum = sum(weights.values())
    if total <= 0 or weight_sum <= 0:
        return {key: 0 for key in weights}
    shares, remainders = {}, []
    for key, weight in weights.items():
        share, remainder = divmod(total * weight, weight_sum)
        shares[key] = share
        remainders.append((remainder, key))
    leftover = total - sum(shares.values())
    for _, key in sorted(remainders, key=lambda r: (-r[0], str(r[1])))[:leftover]:
        shares[key] += 1
    return shares
