"""Unit tests for SleepTools."""

import pytest

from agno.tools.sleep import SleepTools


@pytest.fixture
def sleep_tools():
    return SleepTools()


def test_sleep_returns_a_message(sleep_tools):
    assert sleep_tools.sleep(0) == "Slept for 0.0 seconds"


def test_sleep_accepts_numeric_strings(sleep_tools):
    """Arguments arrive as JSON, so a model can send "0" for a number."""
    assert sleep_tools.sleep("0") == "Slept for 0.0 seconds"


@pytest.mark.parametrize("value", [-1, "-2.5"])
def test_negative_duration_is_reported(sleep_tools, value):
    """`time.sleep` raised ValueError instead of answering the model."""
    result = sleep_tools.sleep(value)

    assert "Invalid sleep duration" in result


@pytest.mark.parametrize("value", ["abc", None, [1]])
def test_non_numeric_duration_is_reported(sleep_tools, value):
    """A non-numeric argument raised TypeError instead of answering the model."""
    result = sleep_tools.sleep(value)

    assert "Invalid sleep duration" in result


def test_disabled_tool_is_not_registered():
    tools = SleepTools(enable_sleep=False)

    assert tools.functions == {}
