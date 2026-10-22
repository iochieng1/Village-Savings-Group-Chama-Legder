import pytest

from chama import security


@pytest.fixture(autouse=True)
def fast_pin_hashing(monkeypatch):
    """Keep PIN hashing realistic in production but quick in tests."""
    monkeypatch.setattr(security, "ITERATIONS", 1_000)
