"""Payment processing — intentionally has zero test coverage."""

def charge(amount_cents: int, card_token: str) -> dict:
    if amount_cents <= 0:
        raise ValueError("amount must be positive")
    return {"status": "charged", "amount_cents": amount_cents, "card_token": card_token}

def refund(charge_id: str, amount_cents: int) -> dict:
    return {"status": "refunded", "charge_id": charge_id, "amount_cents": amount_cents}
