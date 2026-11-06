"""Tests for agno.utils.common.is_empty."""

from agno.utils.common import is_empty


class TestIsEmpty:
    def test_none(self):
        assert is_empty(None) is True

    def test_empty_string(self):
        assert is_empty("") is True

    def test_empty_list(self):
        assert is_empty([]) is True

    def test_empty_dict(self):
        assert is_empty({}) is True

    def test_non_empty_string(self):
        assert is_empty("hello") is False

    def test_non_empty_list(self):
        assert is_empty([1, 2]) is False

    def test_integer(self):
        """Integers don't have len(); should return False, not crash."""
        assert is_empty(42) is False

    def test_float(self):
        """Floats don't have len(); should return False, not crash."""
        assert is_empty(3.14) is False

    def test_boolean(self):
        """Booleans don't have len(); should return False, not crash."""
        assert is_empty(True) is False

    def test_zero(self):
        assert is_empty(0) is False
