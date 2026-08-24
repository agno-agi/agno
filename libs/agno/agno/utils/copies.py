"""Strict-load fidelity check for registry copies."""

from typing import Any, Optional


def copy_divergence(original: Any, copied: Any) -> Optional[str]:
    """How a copy's serialized form differs from its original, or None.

    A deep copy that serializes differently has lost or changed state the
    stored config still names - a subclass whose __init__ swallows kwargs
    turns the inherited deep_copy into an empty shell - so a strict load must
    not dispatch it. Only serialized fields are compared: state to_dict does
    not model is outside what rehydration can promise.
    """
    try:
        original_dict = original.to_dict()
        copied_dict = copied.to_dict()
    except Exception as e:
        return f"the copy could not be compared (to_dict failed: {e})"
    if original_dict == copied_dict:
        return None
    diverging = sorted(
        key for key in set(original_dict) | set(copied_dict) if original_dict.get(key) != copied_dict.get(key)
    )
    return f"the copy diverges from the original on: {', '.join(diverging[:5])}"
