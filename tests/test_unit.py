from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.auth import hash_password, verify_password
from app.finance import commission_kopecks
from app.schemas import AuthCredentials, LotCreate, ParticipantCreate
from app.services import _from_kopecks, _to_kopecks


@pytest.mark.parametrize(
    "price,rate,expected",
    [
        (10000, 0, 0),
        (10000, 10000, 10000),
        (10000, 500, 500),
        (1, 4999, 0),
        (1, 5000, 1),
        (101, 5000, 51),
        (999999999999, 10000, 999999999999),
    ],
)
def test_commission_rounding_and_boundaries(price, rate, expected):
    assert commission_kopecks(price, rate) == expected


@pytest.mark.parametrize("price,rate", [(0, 1), (-1, 100), (100, -1), (100, 10001)])
def test_commission_invalid_arguments(price, rate):
    with pytest.raises(ValueError):
        commission_kopecks(price, rate)


@pytest.mark.parametrize("amount", ["0.01", "150.25", "9999999999.99"])
def test_exact_money_conversion(amount):
    assert _from_kopecks(_to_kopecks(Decimal(amount))) == Decimal(amount)


def test_password_hash_salt_and_verification():
    first = hash_password(" long-password ")
    assert first != hash_password(" long-password ")
    assert verify_password(" long-password ", first)
    assert not verify_password("long-password", first)
    assert not verify_password("wrong", first)


@pytest.mark.parametrize("stored", ["broken", "wrong$1$x$x", "pbkdf2_sha256$bad$x$x"])
def test_invalid_password_hash(stored):
    assert not verify_password("password", stored)


def test_password_is_not_trimmed():
    assert (
        AuthCredentials(username="operator", password=" abcdefgh ").password
        == " abcdefgh "
    )


@pytest.mark.parametrize("email", ["a@b@c.d", "hello", "x@domain", "a b@example.com"])
def test_invalid_email(email):
    with pytest.raises(ValidationError):
        ParticipantCreate(name="Test", email=email)


@pytest.mark.parametrize("price", ["0", "-1", "1.001", "10000000000.00"])
def test_invalid_lot_prices(price):
    with pytest.raises(ValidationError):
        LotCreate(seller_id=1, title="Test", starting_price=price)
