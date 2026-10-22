"""Member PINs: salted PBKDF2 hashes, never stored in clear."""

from __future__ import annotations

import hashlib
import hmac
import secrets

ITERATIONS = 200_000
MAX_FAILED_ATTEMPTS = 5


class WeakPin(ValueError):
    pass


def validate_pin(pin: str) -> None:
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        raise WeakPin("PIN must be 4 to 6 digits")
    if len(set(pin)) == 1:
        raise WeakPin("PIN cannot be one repeated digit")
    digits = [int(d) for d in pin]
    steps = {b - a for a, b in zip(digits, digits[1:])}
    if steps in ({1}, {-1}):
        raise WeakPin("PIN cannot be a simple sequence")


def hash_pin(pin: str, iterations: int | None = None) -> str:
    validate_pin(pin)
    iterations = iterations or ITERATIONS
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def check_pin(pin: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)
