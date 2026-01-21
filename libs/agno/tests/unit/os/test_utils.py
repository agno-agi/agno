"""Unit tests for OS utility functions."""

from datetime import datetime, timezone

from agno.os.utils import to_utc_datetime


def test_returns_none_for_none_input():
    """Test that None input returns None."""
    assert to_utc_datetime(None) is None


def test_converts_int_timestamp():
    """Test conversion of integer Unix timestamp."""
    # Unix timestamp for 2024-01-01 00:00:00 UTC
    timestamp = 1704067200
    result = to_utc_datetime(timestamp)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 1


def test_converts_float_timestamp():
    """Test conversion of float Unix timestamp with microseconds."""
    # Unix timestamp with fractional seconds
    timestamp = 1704067200.123456
    result = to_utc_datetime(timestamp)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.microsecond > 0


def test_preserves_utc_datetime():
    """Test that UTC datetime is returned as-is."""
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = to_utc_datetime(dt)

    assert result is dt


def test_adds_utc_to_naive_datetime():
    """Test that naive datetime gets UTC timezone added."""
    dt = datetime(2024, 1, 1, 12, 0, 0)
    result = to_utc_datetime(dt)

    assert result is not None
    assert result.tzinfo == timezone.utc
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 1
    assert result.hour == 12


def test_preserves_non_utc_timezone():
    """Test that datetime with non-UTC timezone is preserved."""
    from datetime import timedelta

    # Create a datetime with +5:30 offset (IST)
    ist = timezone(timedelta(hours=5, minutes=30))
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=ist)
    result = to_utc_datetime(dt)

    # Should preserve the original timezone
    assert result == dt


def test_handles_zero_timestamp():
    """Test handling of zero timestamp (Unix epoch)."""
    result = to_utc_datetime(0)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.year == 1970
    assert result.month == 1
    assert result.day == 1


def test_handles_negative_timestamp():
    """Test handling of negative timestamp (before Unix epoch)."""
    # One day before Unix epoch
    result = to_utc_datetime(-86400)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.year == 1969
    assert result.month == 12
    assert result.day == 31
