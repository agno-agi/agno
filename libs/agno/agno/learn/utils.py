"""
Learning Machine Utilities
==========================
Helper functions for safe data handling.

All functions are designed to never raise exceptions -
they return None on any failure. This prevents learning
extraction errors from crashing the main agent.
"""

from dataclasses import asdict, fields
from typing import Any, Dict, Optional, Type, TypeVar

T = TypeVar("T")


def _safe_get(data: Any, key: str, default: Any = None) -> Any:
    """Safely get a key from dict-like data.

    Args:
        data: Dict or object with attributes.
        key: Key or attribute name to get.
        default: Value to return if not found.

    Returns:
        The value, or default if not found.
    """
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def _parse_json(data: Any) -> Optional[Dict]:
    """Parse JSON string to dict, or return dict as-is.

    Args:
        data: JSON string, dict, or None.

    Returns:
        Parsed dict, or None if parsing fails.
    """
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        import json

        try:
            return json.loads(data)
        except Exception:
            return None
    return None


def from_dict_safe(cls: Type[T], data: Any) -> Optional[T]:
    """Safely create a dataclass instance from dict-like data.

    Works with any dataclass - automatically handles subclass fields.
    Never raises - returns None on any failure.

    Args:
        cls: The dataclass type to instantiate.
        data: Dict, JSON string, or existing instance.

    Returns:
        Instance of cls, or None if parsing fails.

    Example:
        >>> profile = from_dict_safe(UserProfile, {"user_id": "123"})
        >>> profile.user_id
        '123'
    """
    if data is None:
        return None

    # Already the right type
    if isinstance(data, cls):
        return data

    try:
        # Parse JSON string if needed
        parsed = _parse_json(data)
        if parsed is None:
            return None

        # Get valid field names for this class
        field_names = {f.name for f in fields(cls)}  # type: ignore

        # Filter to only valid fields
        kwargs = {k: v for k, v in parsed.items() if k in field_names}

        return cls(**kwargs)
    except Exception:
        return None


def to_dict_safe(obj: Any) -> Optional[Dict[str, Any]]:
    """Safely convert a dataclass to dict.

    Works with any dataclass. Never raises - returns None on failure.

    Args:
        obj: Dataclass instance to convert.

    Returns:
        Dict representation, or None if conversion fails.

    Example:
        >>> profile = UserProfile(user_id="123")
        >>> to_dict_safe(profile)
        {'user_id': '123', 'name': None, ...}
    """
    if obj is None:
        return None

    try:
        # Already a dict
        if isinstance(obj, dict):
            return obj

        # Has to_dict method
        if hasattr(obj, "to_dict"):
            return obj.to_dict()

        # Is a dataclass
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)

        # Has __dict__
        if hasattr(obj, "__dict__"):
            return dict(obj.__dict__)

        return None
    except Exception:
        return None
