"""Unit tests for CalculatorTools class."""

import json
from unittest.mock import patch

import pytest

from agno.tools.calculator import CalculatorTools


@pytest.fixture
def calculator_tools():
    """Create a CalculatorTools instance with all operations enabled."""
    return CalculatorTools()


@pytest.fixture
def basic_calculator_tools():
    """Create a CalculatorTools instance with only basic operations."""
    return CalculatorTools(include_tools=["add", "subtract", "multiply", "divide"])


def test_initialization_with_selective_operations():
    """Test initialization with only selected operations."""
    # Only enable specific operations
    tools = CalculatorTools(include_tools=["add", "subtract", "exponentiate", "is_prime"])

    # Check which functions are registered
    function_names = [func.name for func in tools.functions.values()]

    assert "add" in function_names
    assert "subtract" in function_names
    assert "multiply" not in function_names
    assert "divide" not in function_names
    assert "exponentiate" in function_names
    assert "factorial" not in function_names
    assert "is_prime" in function_names
    assert "square_root" not in function_names


def test_initialization_with_all_operations():
    """Test initialization with all operations enabled."""
    tools = CalculatorTools()

    function_names = [func.name for func in tools.functions.values()]

    assert "add" in function_names
    assert "subtract" in function_names
    assert "multiply" in function_names
    assert "divide" in function_names
    assert "exponentiate" in function_names
    assert "factorial" in function_names
    assert "is_prime" in function_names
    assert "square_root" in function_names


def test_add_operation(calculator_tools):
    """Test addition operation."""
    result = calculator_tools.add(5, 3)
    result_data = json.loads(result)

    assert result_data["operation"] == "addition"
    assert result_data["result"] == 8

    # Test with negative numbers
    result = calculator_tools.add(-5, 3)
    result_data = json.loads(result)
    assert result_data["result"] == -2

    # Test with floating point numbers
    result = calculator_tools.add(5.5, 3.2)
    result_data = json.loads(result)
    assert result_data["result"] == 8.7


def test_subtract_operation(calculator_tools):
    """Test subtraction operation."""
    result = calculator_tools.subtract(5, 3)
    result_data = json.loads(result)

    assert result_data["operation"] == "subtraction"
    assert result_data["result"] == 2

    # Test with negative numbers
    result = calculator_tools.subtract(-5, 3)
    result_data = json.loads(result)
    assert result_data["result"] == -8

    # Test with floating point numbers
    result = calculator_tools.subtract(5.5, 3.2)
    result_data = json.loads(result)
    assert result_data["result"] == 2.3


def test_multiply_operation(calculator_tools):
    """Test multiplication operation."""
    result = calculator_tools.multiply(5, 3)
    result_data = json.loads(result)

    assert result_data["operation"] == "multiplication"
    assert result_data["result"] == 15

    # Test with negative numbers
    result = calculator_tools.multiply(-5, 3)
    result_data = json.loads(result)
    assert result_data["result"] == -15

    # Test with floating point numbers
    result = calculator_tools.multiply(5.5, 3.2)
    result_data = json.loads(result)
    assert result_data["result"] == 17.6


def test_divide_operation(calculator_tools):
    """Test division operation."""
    result = calculator_tools.divide(6, 3)
    result_data = json.loads(result)

    assert result_data["operation"] == "division"
    assert result_data["result"] == 2

    # Test with floating point result
    result = calculator_tools.divide(5, 2)
    result_data = json.loads(result)
    assert result_data["result"] == 2.5

    # Test division by zero
    result = calculator_tools.divide(5, 0)
    result_data = json.loads(result)
    assert "error" in result_data
    assert "Division by zero is undefined" in result_data["error"]


def test_exponentiate_operation(calculator_tools):
    """Test exponentiation operation."""
    result = calculator_tools.exponentiate(2, 3)
    result_data = json.loads(result)

    assert result_data["operation"] == "exponentiation"
    assert result_data["result"] == 8

    # Test with negative exponent
    result = calculator_tools.exponentiate(2, -2)
    result_data = json.loads(result)
    assert result_data["result"] == 0.25

    # Test with floating point numbers
    result = calculator_tools.exponentiate(2.5, 2)
    result_data = json.loads(result)
    assert result_data["result"] == 6.25


def test_factorial_operation(calculator_tools):
    """Test factorial operation."""
    result = calculator_tools.factorial(5)
    result_data = json.loads(result)

    assert result_data["operation"] == "factorial"
    assert result_data["result"] == 120

    # Test with zero
    result = calculator_tools.factorial(0)
    result_data = json.loads(result)
    assert result_data["result"] == 1

    # Test with negative number
    result = calculator_tools.factorial(-1)
    result_data = json.loads(result)
    assert "error" in result_data
    assert "Factorial of a negative number is undefined" in result_data["error"]


def test_is_prime_operation(calculator_tools):
    """Test prime number checking operation."""
    # Test with prime number
    result = calculator_tools.is_prime(7)
    result_data = json.loads(result)

    assert result_data["operation"] == "prime_check"
    assert result_data["result"] is True

    # Test with non-prime number
    result = calculator_tools.is_prime(4)
    result_data = json.loads(result)
    assert result_data["result"] is False

    # Test with 1 (not prime by definition)
    result = calculator_tools.is_prime(1)
    result_data = json.loads(result)
    assert result_data["result"] is False

    # Test with 0 (not prime)
    result = calculator_tools.is_prime(0)
    result_data = json.loads(result)
    assert result_data["result"] is False

    # Test with negative number (not prime)
    result = calculator_tools.is_prime(-5)
    result_data = json.loads(result)
    assert result_data["result"] is False


def test_square_root_operation(calculator_tools):
    """Test square root operation."""
    result = calculator_tools.square_root(9)
    result_data = json.loads(result)

    assert result_data["operation"] == "square_root"
    assert result_data["result"] == 3

    # Test with non-perfect square
    result = calculator_tools.square_root(2)
    result_data = json.loads(result)
    assert result_data["result"] == pytest.approx(1.4142, 0.0001)

    # Test with negative number
    result = calculator_tools.square_root(-1)
    result_data = json.loads(result)
    assert "error" in result_data
    assert "Square root of a negative number is undefined" in result_data["error"]


def test_basic_calculator_has_only_basic_operations(basic_calculator_tools):
    """Test that basic calculator only has basic operations."""
    function_names = [func.name for func in basic_calculator_tools.functions.values()]

    # Basic operations should be included
    assert "add" in function_names
    assert "subtract" in function_names
    assert "multiply" in function_names
    assert "divide" in function_names

    # Advanced operations should not be included
    assert "exponentiate" not in function_names
    assert "factorial" not in function_names
    assert "is_prime" not in function_names
    assert "square_root" not in function_names


def test_error_logging(calculator_tools):
    """Test that errors are properly logged."""
    with patch("agno.tools.calculator.log_error") as mock_log_error:
        calculator_tools.divide(5, 0)
        mock_log_error.assert_called_once_with("Attempt to divide by zero")

        mock_log_error.reset_mock()
        calculator_tools.factorial(-1)
        mock_log_error.assert_called_once_with("Attempt to calculate factorial of a negative number")

        mock_log_error.reset_mock()
        calculator_tools.square_root(-4)
        mock_log_error.assert_called_once_with("Attempt to calculate square root of a negative number")


def test_large_numbers(calculator_tools):
    """Test operations with large numbers."""
    # Test factorial with large number
    result = calculator_tools.factorial(20)
    result_data = json.loads(result)
    assert result_data["result"] == 2432902008176640000

    # Test exponentiation with large numbers
    result = calculator_tools.exponentiate(2, 30)
    result_data = json.loads(result)
    assert result_data["result"] == 1073741824


def test_division_exception_handling(calculator_tools):
    """Test handling of exceptions in division."""
    with patch("math.pow", side_effect=Exception("Test exception")):
        result = calculator_tools.divide(1, 0)
        result_data = json.loads(result)
        assert "error" in result_data


@pytest.mark.parametrize(
    "operation,args,expected",
    [
        ("add", ("10", "5"), 15),
        ("subtract", ("10", "5"), 5),
        ("multiply", ("10", "5"), 50),
        ("divide", ("10", "5"), 2.0),
        ("exponentiate", ("2", "10"), 1024.0),
        ("add", ("2.5", "2.5"), 5.0),
    ],
)
def test_numeric_strings_are_used_as_numbers(calculator_tools, operation, args, expected):
    """Numeric arguments sent as strings must be operated on, not concatenated."""
    result = json.loads(getattr(calculator_tools, operation)(*args))

    assert result["result"] == expected
    assert type(result["result"]) is type(expected)


def test_integer_arguments_keep_returning_integers(calculator_tools):
    """Converting arguments must not turn an integer result into a float."""
    for operation, args, expected in [
        ("add", (1, 2), 3),
        ("subtract", (5, 2), 3),
        ("multiply", (3, 4), 12),
    ]:
        result = json.loads(getattr(calculator_tools, operation)(*args))

        assert result["result"] == expected
        assert isinstance(result["result"], int)


def test_add_does_not_concatenate_string_arguments(calculator_tools):
    """`add("10", "5")` used to return the string "105"."""
    result = json.loads(calculator_tools.add("10", "5"))

    assert result["result"] == 15


@pytest.mark.parametrize("operation,args", [("add", ("abc", 5)), ("multiply", (None, 5)), ("divide", (True, 2))])
def test_non_numeric_arguments_return_an_error(calculator_tools, operation, args):
    """A non-numeric argument returns the shared error payload."""
    result = json.loads(getattr(calculator_tools, operation)(*args))

    assert "error" in result
    assert "result" not in result


def test_whole_numbers_are_accepted_where_integers_are_expected(calculator_tools):
    """Whole numbers sent as strings or floats are usable by the integer operations."""
    assert json.loads(calculator_tools.factorial("5"))["result"] == 120
    assert json.loads(calculator_tools.is_prime("7"))["result"] is True


@pytest.mark.parametrize("value", [4.5, 2.5, "three"])
def test_prime_check_rejects_numbers_that_are_not_whole(calculator_tools, value):
    """`is_prime(4.5)` used to report True because the remainder loop found no divisor."""
    result = json.loads(calculator_tools.is_prime(value))

    assert "error" in result
    assert "result" not in result


@pytest.mark.parametrize("args", [(-8, 1 / 3), (0, -1)])
def test_exponentiate_returns_an_error_instead_of_raising(calculator_tools, args):
    """`math.pow` raised a ValueError for inputs outside its domain."""
    result = json.loads(calculator_tools.exponentiate(*args))

    assert "error" in result
