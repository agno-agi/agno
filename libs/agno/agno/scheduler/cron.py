"""Cron expression utilities for the scheduler."""

import time
from datetime import datetime
from typing import Optional

try:
    from croniter import croniter  # type: ignore[import-untyped]
except ImportError:
    croniter = None  # type: ignore[assignment, misc]

try:
    import pytz
except ImportError:
    pytz = None  # type: ignore[assignment]


def _require_croniter() -> None:
    if croniter is None:
        raise ImportError("`croniter` not installed. Please install it using `pip install agno[scheduler]`")


def _require_pytz() -> None:
    if pytz is None:
        raise ImportError("`pytz` not installed. Please install it using `pip install agno[scheduler]`")


def validate_cron_expr(cron_expr: str) -> bool:
    """Validate a cron expression.

    Args:
        cron_expr: Cron expression string (5-field).

    Returns:
        True if valid, False otherwise.
    """
    _require_croniter()
    return croniter.is_valid(cron_expr)


def validate_timezone(tz: str) -> bool:
    """Validate a timezone string.

    Args:
        tz: Timezone string (e.g. 'UTC', 'America/New_York').

    Returns:
        True if valid, False otherwise.
    """
    _require_pytz()
    try:
        pytz.timezone(tz)
        return True
    except pytz.exceptions.UnknownTimeZoneError:
        return False


def compute_next_run(
    cron_expr: str,
    timezone_str: str = "UTC",
    after_epoch: Optional[int] = None,
) -> int:
    """Compute the next run time as epoch seconds.

    Uses a monotonicity guard: the returned value is always at least
    ``int(time.time()) + 1`` to avoid scheduling in the past.

    Args:
        cron_expr: Cron expression string (5-field).
        timezone_str: Timezone for evaluation (default: UTC).
        after_epoch: Epoch seconds to compute the next run after.
            If None, uses the current time.

    Returns:
        Next run time as epoch seconds.
    """
    _require_croniter()
    _require_pytz()

    tz = pytz.timezone(timezone_str)

    if after_epoch is not None:
        base_dt = datetime.fromtimestamp(after_epoch, tz=tz)
    else:
        base_dt = datetime.now(tz=tz)

    cron = croniter(cron_expr, base_dt)
    next_dt = cron.get_next(datetime)

    computed = int(next_dt.timestamp())

    # Monotonicity guard: never schedule in the past
    minimum = int(time.time()) + 1
    return max(computed, minimum)
