import pytest

from chama import money, phone


@pytest.mark.parametrize(
    "raw,cents",
    [("1500", 150000), ("1,500", 150000), ("250.5", 25050), ("250.50", 25050), ("KES 1,000,000", 100000000), (200, 20000)],
)
def test_parse(raw, cents):
    assert money.parse(raw) == cents


@pytest.mark.parametrize("raw", ["", "0", "-100", "1,50", "12.345", "abc", "1e3", 0, -5])
def test_parse_rejects(raw):
    with pytest.raises(money.InvalidAmount):
        money.parse(raw)


def test_fmt():
    assert money.fmt(150000) == "KES 1,500"
    assert money.fmt(25050) == "KES 250.50"
    assert money.fmt(-5) == "-KES 0.05"


def test_percent_of_rounds_half_up():
    assert money.percent_of(100000, 1000) == 10000
    assert money.percent_of(5, 1000) == 1  # 0.5 cent rounds up


def test_split_pro_rata_adds_up_exactly():
    shares = money.split_pro_rata(1000, {"a": 1, "b": 1, "c": 1})
    assert sum(shares.values()) == 1000
    assert sorted(shares.values()) == [333, 333, 334]
    assert money.split_pro_rata(0, {"a": 1}) == {"a": 0}
    assert money.split_pro_rata(100, {"a": 0}) == {"a": 0}
    assert money.split_pro_rata(10000, {"a": 30000, "b": 10000}) == {"a": 7500, "b": 2500}


@pytest.mark.parametrize("raw", ["0712345678", "+254712345678", "254112345678", "0712 345 678"])
def test_phone_normalise(raw):
    assert phone.normalise(raw).startswith("+254")


@pytest.mark.parametrize("raw", ["", "0812345678", "071234567"])
def test_phone_rejects(raw):
    with pytest.raises(phone.InvalidPhone):
        phone.normalise(raw)
