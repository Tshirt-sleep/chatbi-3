import pytest
from backend.chatbi.seed import to_cents


def test_decimal_csv_amount_converts_to_integer_cents() -> None:
    assert to_cents("257984.80") == 25_798_480


def test_blank_optional_amount_is_zero() -> None:
    assert to_cents("") == 0


def test_money_conversion_rejects_negative_or_extra_precision() -> None:
    with pytest.raises(ValueError):
        to_cents("-0.01")
    with pytest.raises(ValueError):
        to_cents("2.505")
