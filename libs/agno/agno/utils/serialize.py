"""JSON serialization utilities for handling datetime and enum objects."""

from datetime import date, datetime, time
from enum import Enum
from typing import Any


def json_serializer(obj: Any) -> Any:
    """Custom JSON serializer for objects not serializable by default json module.

    Handles:
    - datetime, date, time objects -> ISO format strings
    - Enum objects -> their values (or names if values are not JSON-serializable)
    - All other objects -> string representation

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable representation of the object
    """
    # Datetime like
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()

    # Enums
    if isinstance(obj, Enum):
        v = obj.value
        return v if isinstance(v, (str, int, float, bool, type(None))) else obj.name

    # Fallback to string
    return str(obj)
