"""Shipping policy used as input by the harness cookbooks (not an agent example)."""


def shipping_fee(subtotal: int) -> int:
    """Charge eight dollars below the hundred-dollar free-shipping threshold."""
    if subtotal < 0:
        raise ValueError("subtotal must be non-negative")
    return 0 if subtotal >= 100 else 8
