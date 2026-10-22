import pytest

from chama import security


def test_hash_and_check():
    stored = security.hash_pin("4826")
    assert stored.startswith("pbkdf2_sha256$1000$")
    assert security.check_pin("4826", stored)
    assert not security.check_pin("4827", stored)


def test_same_pin_gets_different_salt():
    assert security.hash_pin("4826") != security.hash_pin("4826")


@pytest.mark.parametrize("pin", ["123", "1234567", "12a4", "1111", "1234", "4321", "56789"])
def test_weak_pins_rejected(pin):
    with pytest.raises(security.WeakPin):
        security.hash_pin(pin)


@pytest.mark.parametrize("stored", ["", "garbage", "md5$1$aa$bb"])
def test_check_pin_handles_bad_hashes(stored):
    assert not security.check_pin("4826", stored)
