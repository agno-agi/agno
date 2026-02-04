"""Cron utilities for schedule management.

This module provides utilities for working with cron expressions,
including validation and calculating next run times.

Requires the 'croniter' package: pip install croniter
"""

from datetime import datetime, timezone
from typing import Optional

from agno.utils.log import log_error


def _get_croniter():
    """Lazily import croniter to avoid import errors if not installed."""
    try:
        from croniter import croniter

        return croniter
    except ImportError:
        raise ImportError(
            "croniter is required for scheduler functionality. Install it with: pip install agno[scheduler]"
        )


def validate_cron_expr(cron_expr: str) -> bool:
    """Validate a cron expression.

    Args:
        cron_expr: The cron expression to validate (e.g., '0 3 * * *').

    Returns:
        True if the expression is valid, False otherwise.
    """
    try:
        croniter = _get_croniter()
        croniter(cron_expr)
        return True
    except (ValueError, KeyError):
        return False


def calculate_next_run(
    cron_expr: str,
    tz: str = "UTC",
    base_time: Optional[datetime] = None,
) -> int:
    """Calculate the next run time for a cron expression.

    Args:
        cron_expr: The cron expression (e.g., '0 3 * * *' for 3 AM daily).
        tz: The timezone name (e.g., 'America/New_York', 'UTC').
        base_time: The base time to calculate from. Defaults to now.

    Returns:
        Epoch seconds for the next run time.

    Raises:
        ValueError: If the cron expression is invalid.
        ImportError: If croniter is not installed.
    """
    try:
        import pytz
    except ImportError:
        pytz = None

    croniter = _get_croniter()

    # Get the base time in the specified timezone
    if base_time is None:
        base_time = datetime.now(timezone.utc)

    # Convert to the specified timezone if pytz is available
    if pytz is not None and tz != "UTC":
        try:
            target_tz = pytz.timezone(tz)
            base_time = base_time.astimezone(target_tz)
        except Exception as e:
            log_error(f"Invalid timezone '{tz}', using UTC: {e}")
            base_time = base_time.astimezone(timezone.utc)
    else:
        base_time = base_time.astimezone(timezone.utc)

    try:
        cron = croniter(cron_expr, base_time)
        next_run = cron.get_next(datetime)

        # Convert to UTC and return as epoch seconds
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
        else:
            next_run = next_run.astimezone(timezone.utc)

        return int(next_run.timestamp())

    except Exception as e:
        raise ValueError(f"Invalid cron expression '{cron_expr}': {e}")


def get_cron_description(cron_expr: str) -> str:
    """Get a human-readable description of a cron expression.

    Args:
        cron_expr: The cron expression.

    Returns:
        A human-readable description.
    """
    # Common patterns
    patterns = {
        "* * * * *": "Every minute",
        "0 * * * *": "Every hour",
        "0 0 * * *": "Every day at midnight",
        "0 0 * * 0": "Every Sunday at midnight",
        "0 0 1 * *": "First day of every month at midnight",
    }

    if cron_expr in patterns:
        return patterns[cron_expr]

    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr

    minute, hour, day, month, weekday = parts

    desc_parts = []

    # Minute
    if minute == "*":
        desc_parts.append("every minute")
    elif minute == "0":
        pass  # Will be covered by hour
    else:
        desc_parts.append(f"at minute {minute}")

    # Hour
    if hour == "*":
        if minute != "*":
            desc_parts.append("every hour")
    elif hour != "*":
        desc_parts.append(f"at {hour}:{'00' if minute == '0' else minute}")

    # Day of month
    if day != "*":
        desc_parts.append(f"on day {day}")

    # Month
    if month != "*":
        months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        try:
            month_name = months[int(month)]
            desc_parts.append(f"in {month_name}")
        except (ValueError, IndexError):
            desc_parts.append(f"in month {month}")

    # Day of week
    if weekday != "*":
        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        try:
            day_name = days[int(weekday)]
            desc_parts.append(f"on {day_name}")
        except (ValueError, IndexError):
            desc_parts.append(f"on weekday {weekday}")

    return " ".join(desc_parts) if desc_parts else cron_expr
