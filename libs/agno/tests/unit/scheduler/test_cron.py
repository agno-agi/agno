"""Unit tests for cron utilities."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest


class TestValidateCronExpr:
    """Tests for validate_cron_expr function."""

    def test_validate_valid_cron_expressions(self):
        """Test validation of valid cron expressions."""
        from agno.scheduler.cron import validate_cron_expr

        valid_expressions = [
            "* * * * *",  # Every minute
            "0 * * * *",  # Every hour
            "0 0 * * *",  # Every day at midnight
            "0 3 * * *",  # Every day at 3 AM
            "0 0 * * 0",  # Every Sunday at midnight
            "0 0 1 * *",  # First day of every month
            "*/5 * * * *",  # Every 5 minutes
            "0 9-17 * * 1-5",  # 9 AM to 5 PM, Monday to Friday
            "30 4 1,15 * *",  # 4:30 AM on 1st and 15th
        ]

        for expr in valid_expressions:
            assert validate_cron_expr(expr) is True, f"Expected '{expr}' to be valid"

    def test_validate_invalid_cron_expressions(self):
        """Test validation of invalid cron expressions."""
        from agno.scheduler.cron import validate_cron_expr

        # Note: croniter is lenient - it accepts 6-field expressions (seconds),
        # and some out-of-range values may wrap. We test expressions
        # that croniter actually rejects.
        invalid_expressions = [
            "",  # Empty
            "invalid",  # Not a cron expression
            "* * *",  # Too few fields
            "60 * * * *",  # Invalid minute (0-59)
            "* * 32 * *",  # Invalid day of month (1-31)
            "* * * 13 *",  # Invalid month (1-12)
        ]

        for expr in invalid_expressions:
            assert validate_cron_expr(expr) is False, f"Expected '{expr}' to be invalid"

    def test_validate_croniter_not_installed(self):
        """Test behavior when croniter is not installed."""
        from agno.scheduler.cron import validate_cron_expr

        with patch("agno.scheduler.cron._get_croniter") as mock_get:
            mock_get.side_effect = ImportError("croniter not installed")

            with pytest.raises(ImportError, match="croniter"):
                validate_cron_expr("* * * * *")


class TestCalculateNextRun:
    """Tests for calculate_next_run function."""

    def test_calculate_next_run_basic(self):
        """Test basic next run calculation."""
        from agno.scheduler.cron import calculate_next_run

        # Get next run for every minute
        next_run = calculate_next_run("* * * * *")

        # Should be within the next 60 seconds
        now = int(datetime.now(timezone.utc).timestamp())
        assert next_run > now
        assert next_run <= now + 60

    def test_calculate_next_run_with_base_time(self):
        """Test next run calculation with specific base time."""
        from agno.scheduler.cron import calculate_next_run

        # Base time: 2024-01-15 10:30:00 UTC
        base_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        # Every hour at minute 0
        next_run = calculate_next_run("0 * * * *", base_time=base_time)

        # Expected: 2024-01-15 11:00:00 UTC
        expected = datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
        assert next_run == int(expected.timestamp())

    def test_calculate_next_run_daily(self):
        """Test next run calculation for daily schedule."""
        from agno.scheduler.cron import calculate_next_run

        # Base time: 2024-01-15 10:30:00 UTC
        base_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        # Every day at 3 AM
        next_run = calculate_next_run("0 3 * * *", base_time=base_time)

        # Expected: 2024-01-16 03:00:00 UTC (next day since 3 AM already passed)
        expected = datetime(2024, 1, 16, 3, 0, 0, tzinfo=timezone.utc)
        assert next_run == int(expected.timestamp())

    def test_calculate_next_run_invalid_expression(self):
        """Test that invalid expressions raise ValueError."""
        from agno.scheduler.cron import calculate_next_run

        with pytest.raises(ValueError, match="Invalid cron expression"):
            calculate_next_run("invalid")

    def test_calculate_next_run_returns_epoch_seconds(self):
        """Test that next run is returned as integer epoch seconds."""
        from agno.scheduler.cron import calculate_next_run

        next_run = calculate_next_run("* * * * *")

        assert isinstance(next_run, int)
        assert next_run > 0


class TestGetCronDescription:
    """Tests for get_cron_description function."""

    def test_common_patterns(self):
        """Test descriptions for common cron patterns."""
        from agno.scheduler.cron import get_cron_description

        assert get_cron_description("* * * * *") == "Every minute"
        assert get_cron_description("0 * * * *") == "Every hour"
        assert get_cron_description("0 0 * * *") == "Every day at midnight"
        assert get_cron_description("0 0 * * 0") == "Every Sunday at midnight"
        assert get_cron_description("0 0 1 * *") == "First day of every month at midnight"

    def test_custom_time(self):
        """Test description for custom time patterns."""
        from agno.scheduler.cron import get_cron_description

        desc = get_cron_description("0 3 * * *")
        assert "3:00" in desc

    def test_invalid_format_returns_original(self):
        """Test that invalid format returns original expression."""
        from agno.scheduler.cron import get_cron_description

        # Too few parts
        assert get_cron_description("* * *") == "* * *"
        # Too many parts
        assert get_cron_description("* * * * * *") == "* * * * * *"
