"""Tests for agno.scheduler.cron — cron validation, next_run computation, timezone handling."""

import time

import pytest

try:
    import croniter  # noqa: F401
    import pytz  # noqa: F401

    HAS_SCHEDULER_DEPS = True
except ImportError:
    HAS_SCHEDULER_DEPS = False

pytestmark = pytest.mark.skipif(not HAS_SCHEDULER_DEPS, reason="croniter/pytz not installed")

from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone  # noqa: E402


class TestValidateCronExpr:
    def test_valid_every_minute(self):
        assert validate_cron_expr("* * * * *") is True

    def test_valid_every_5_minutes(self):
        assert validate_cron_expr("*/5 * * * *") is True

    def test_valid_specific_time(self):
        assert validate_cron_expr("30 9 * * 1-5") is True

    def test_valid_monthly(self):
        assert validate_cron_expr("0 0 1 * *") is True

    def test_six_fields_with_seconds(self):
        # croniter supports 6-field expressions (with seconds)
        assert validate_cron_expr("* * * * * *") is True

    def test_invalid_out_of_range(self):
        assert validate_cron_expr("60 * * * *") is False

    def test_invalid_garbage(self):
        assert validate_cron_expr("not a cron") is False

    def test_empty_string(self):
        assert validate_cron_expr("") is False


class TestValidateTimezone:
    def test_utc(self):
        assert validate_timezone("UTC") is True

    def test_us_eastern(self):
        assert validate_timezone("US/Eastern") is True

    def test_america_new_york(self):
        assert validate_timezone("America/New_York") is True

    def test_asia_tokyo(self):
        assert validate_timezone("Asia/Tokyo") is True

    def test_invalid(self):
        assert validate_timezone("Not/A/Timezone") is False

    def test_empty(self):
        assert validate_timezone("") is False


class TestComputeNextRun:
    def test_returns_integer(self):
        result = compute_next_run("* * * * *")
        assert isinstance(result, int)

    def test_in_the_future(self):
        result = compute_next_run("* * * * *")
        assert result > int(time.time())

    def test_monotonicity_guard(self):
        """next_run_at should always be >= now + 1."""
        past_epoch = int(time.time()) - 3600
        result = compute_next_run("* * * * *", after_epoch=past_epoch)
        assert result >= int(time.time()) + 1

    def test_after_epoch(self):
        """When after_epoch is provided, next run should be after it."""
        after = int(time.time()) + 7200
        result = compute_next_run("* * * * *", after_epoch=after)
        assert result > after

    def test_timezone_affects_result(self):
        """Different timezones should produce different results for time-specific crons."""
        result_utc = compute_next_run("0 3 * * *", timezone_str="UTC")
        result_tokyo = compute_next_run("0 3 * * *", timezone_str="Asia/Tokyo")
        assert result_utc != result_tokyo

    def test_specific_cron_from_fixed_time(self):
        """Compute next run for a specific cron from a known time."""
        after = 1735689600  # 2025-01-01 00:00:00 UTC
        result = compute_next_run("0 * * * *", after_epoch=after)
        assert result >= 1735693200  # 2025-01-01 01:00:00 UTC

    def test_default_timezone_is_utc(self):
        result1 = compute_next_run("0 12 * * *")
        result2 = compute_next_run("0 12 * * *", timezone_str="UTC")
        assert result1 == result2
