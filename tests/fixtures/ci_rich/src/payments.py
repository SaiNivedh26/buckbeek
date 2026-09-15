"""Deliberately untested module."""


def charge(amount_cents: int) -> dict:
    if amount_cents <= 0:
        raise ValueError("amount must be positive")
    return {"status": "charged", "amount": amount_cents}
