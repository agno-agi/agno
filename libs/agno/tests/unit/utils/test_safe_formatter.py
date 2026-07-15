"""Tests for SafeFormatter."""

from agno.utils.safe_formatter import SafeFormatter


def test_positional_fields_use_positional_arguments():
    formatter = SafeFormatter()

    assert formatter.format("{0} {name}", "hello", name="world") == "hello world"
    assert formatter.format("{} {name}", "hello", name="world") == "hello world"


def test_missing_named_fields_keep_existing_fallback():
    assert SafeFormatter().format("{missing}") == "missing"
