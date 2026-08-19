"""Unit tests for agno.utils.dttm helpers."""

from datetime import datetime, timezone

from agno.utils.dttm import (
    current_datetime,
    current_datetime_utc,
    current_datetime_utc_str,
    now_epoch_s,
    parse_datetime_utc,
    to_epoch_s,
)


def test_current_datetime_is_utc_aware():
    """current_datetime must return a UTC-aware datetime, not a naive local one."""
    now = current_datetime()
    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(now)


def test_current_datetime_utc_is_aware():
    now = current_datetime_utc()
    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(now)


def test_current_datetime_utc_str_carries_offset():
    """The string form must include an explicit UTC offset so consumers can
    tell it apart from naive local wall-clock strings."""
    s = current_datetime_utc_str()
    assert s.endswith("+00:00"), f"expected UTC offset, got {s!r}"
    # Seconds precision only (no microseconds), matching the pre-existing format.
    assert "." not in s
    # Round-trips through the module's own parser.
    parsed = parse_datetime_utc(s)
    assert parsed.tzinfo is not None


def test_now_epoch_s_is_utc_based():
    """now_epoch_s must agree with a UTC-aware reference clock."""
    epoch = now_epoch_s()
    ref = int(datetime.now(timezone.utc).timestamp())
    assert abs(epoch - ref) <= 1


def test_to_epoch_s_naive_datetime_assumed_utc():
    """A naive datetime fed to to_epoch_s is interpreted as UTC (documented
    contract), so a UTC-aware datetime of the same instant maps to the same
    epoch."""
    aware = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 1, 1, 0, 0, 0)
    assert to_epoch_s(aware) == to_epoch_s(naive)
