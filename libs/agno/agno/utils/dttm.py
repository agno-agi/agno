from datetime import datetime, timezone
from typing import Any, Union


def parse_datetime_utc(value: Any) -> datetime:
    """Parse a datetime or ISO 8601 string and return a UTC-aware datetime.

    - datetime with tzinfo -> converted to UTC
    - datetime without tzinfo -> assumed UTC
    - str -> parsed via fromisoformat, then converted to UTC
    - Other types -> raises TypeError

    Raises:
        TypeError: If *value* is not a datetime or str.
        ValueError: If a string cannot be parsed as ISO 8601.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        return value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)
    raise TypeError(f"Unsupported datetime value: {type(value)}")


def current_datetime() -> datetime:
    return datetime.now()


def current_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


def current_datetime_utc_str() -> str:
    return current_datetime_utc().strftime("%Y-%m-%dT%H:%M:%S")


def now_epoch_s() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def to_epoch_s(value: Union[int, float, str, datetime]) -> int:
    """Normalize various datetime representations to epoch seconds (UTC)."""

    if isinstance(value, (int, float)):
        # assume value is already in seconds
        return int(value)

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ValueError(f"Unsupported datetime string: {value!r}") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    raise TypeError(f"Unsupported datetime value: {type(value)}")
