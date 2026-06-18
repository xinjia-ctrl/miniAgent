from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from shopcart import apply_discount


def test_apply_discount_uses_percent_not_absolute_amount() -> None:
    assert apply_discount(100, 20) == 80


def test_apply_discount_keeps_full_price_for_zero_percent() -> None:
    assert apply_discount(42, 0) == 42


def test_apply_discount_rejects_invalid_percent() -> None:
    with pytest.raises(ValueError):
        apply_discount(100, 120)
