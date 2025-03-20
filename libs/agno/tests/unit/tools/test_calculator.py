"""Unit tests for CalculatorTools class."""

import json
from unittest.mock import patch

import pytest

from agno.tools.calculator import CalculatorTools


@pytest.fixture
def calculator_tools():
    """Create a CalculatorTools instance with all operations enabled."""
    return CalculatorTools(enable_all=True)


@pytest.fixture
def basic_calculator_tools():
    """Create a CalculatorTools instance with only basic operations."""
    return CalculatorTools()


def test_initialization_with_selective_operations():
    """Test initialization with only selected operations."""
    # Only enable specific operations
    tools = CalculatorTools(
        add=True,
        subtract=True,
        multiply=False,
        divide=False,
        exponentiate=True,
        factorial=False,
        is_prime=True,
        square_root=False,
    )

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
    tools = CalculatorTools(enable_all=True)

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
    with patch("agno.tools.calculator.logger.error") as mock_logger:
        calculator_tools.divide(5, 0)
        mock_logger.assert_called_once_with("Attempt to divide by zero")

        mock_logger.reset_mock()
        calculator_tools.factorial(-1)
        mock_logger.assert_called_once_with("Attempt to calculate factorial of a negative number")

        mock_logger.reset_mock()
        calculator_tools.square_root(-4)
        mock_logger.assert_called_once_with("Attempt to calculate square root of a negative number")


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
