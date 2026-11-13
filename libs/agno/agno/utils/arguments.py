from typing import Any


def tool_argument_values_equal(actual: Any, expected: Any) -> bool:
    """Compare argument values recursively, keeping booleans distinct from numbers.

    Numeric equality (including int/float pairs) is preserved. Containers still
    require equal contents; subset matching belongs to the top-level argument spec.
    """
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            tool_argument_values_equal(value, expected[key]) for key, value in actual.items()
        )
    if (isinstance(actual, list) and isinstance(expected, list)) or (
        isinstance(actual, tuple) and isinstance(expected, tuple)
    ):
        return len(actual) == len(expected) and all(
            tool_argument_values_equal(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected
