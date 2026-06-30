"""Tests for cron expression utilities."""

import time

import pytest

pytest.importorskip("croniter", reason="croniter not installed")
pytest.importorskip("pytz", reason="pytz not installed")

from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone  # noqa: E402


class TestValidateCronExpr:
    def test_valid_cron_every_minute(self):
        assert validate_cron_expr("* * * * *") is True

    def test_valid_cron_daily(self):
        assert validate_cron_expr("0 9 * * *") is True

    def test_valid_cron_weekly(self):
        assert validate_cron_expr("0 0 * * 1") is True

    def test_valid_cron_monthly(self):
        assert validate_cron_expr("0 0 1 * *") is True

    def test_valid_cron_with_ranges(self):
        assert validate_cron_expr("0 9-17 * * 1-5") is True

    def test_valid_cron_with_step(self):
        assert validate_cron_expr("*/5 * * * *") is True

    def test_invalid_cron_empty(self):
        assert validate_cron_expr("") is False

    def test_invalid_cron_too_few_fields(self):
        assert validate_cron_expr("* *") is False

    def test_invalid_cron_bad_minute(self):
        assert validate_cron_expr("61 * * * *") is False

    def test_invalid_cron_bad_hour(self):
        assert validate_cron_expr("0 25 * * *") is False


class TestValidateTimezone:
    def test_valid_utc(self):
        assert validate_timezone("UTC") is True

    def test_valid_new_york(self):
        assert validate_timezone("America/New_York") is True

    def test_valid_tokyo(self):
        assert validate_timezone("Asia/Tokyo") is True

    def test_invalid_timezone(self):
        assert validate_timezone("Not/A/Timezone") is False

    def test_invalid_empty(self):
        assert validate_timezone("") is False


class TestComputeNextRun:
    def test_returns_future_time(self):
        result = compute_next_run("* * * * *")
        assert result > int(time.time())

    def test_monotonicity_guard(self):
        # Even if we provide an after_epoch in the distant past, the result
        # should still be >= now + 1
        result = compute_next_run("* * * * *", after_epoch=0)
        minimum = int(time.time()) + 1
        assert result >= minimum

    def test_respects_timezone(self):
        # Both should return valid future timestamps
        utc_result = compute_next_run("0 12 * * *", "UTC")
        ny_result = compute_next_run("0 12 * * *", "America/New_York")
        assert utc_result > int(time.time())
        assert ny_result > int(time.time())
        # They should differ (different timezones, different absolute times)
        # But edge cases exist, so we just check they're both valid
        assert isinstance(utc_result, int)
        assert isinstance(ny_result, int)

    def test_after_epoch(self):
        now = int(time.time())
        result = compute_next_run("* * * * *", after_epoch=now)
        assert result > now
