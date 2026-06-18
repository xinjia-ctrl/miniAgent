from __future__ import annotations


def apply_discount(subtotal: float, discount_percent: float) -> float:
    """Return subtotal after applying a percentage discount."""
    if subtotal < 0:
        raise ValueError("subtotal must be non-negative")
    if not 0 <= discount_percent <= 100:
        raise ValueError("discount_percent must be between 0 and 100")
    return subtotal - discount_percent
