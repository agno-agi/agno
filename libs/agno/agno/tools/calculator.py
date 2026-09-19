import json
import math
from typing import Any, Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


def _to_number(value: Any) -> Optional[float]:
    """Return ``value`` as a number, or ``None`` when it is not numeric.

    Tool arguments arrive as JSON and are not validated against the declared
    types, so a model or MCP client that sends ``"10"`` for a numeric parameter
    reaches these methods as a string.
    """
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_integer(value: Any) -> Optional[int]:
    """Return ``value`` as an int when it is a whole number, otherwise ``None``."""
    number = _to_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


class CalculatorTools(Toolkit):
    def __init__(
        self,
        **kwargs,
    ):
        tools: List[Callable] = [
            self.add,
            self.subtract,
            self.multiply,
            self.divide,
            self.exponentiate,
            self.factorial,
            self.is_prime,
            self.square_root,
        ]

        # Initialize the toolkit with auto-registration enabled
        super().__init__(name="calculator", tools=tools, **kwargs)

    @staticmethod
    def _as_two_numbers(a: Any, b: Any) -> Optional[List[float]]:
        """Return both arguments as numbers, or ``None`` when either is not numeric."""
        first, second = _to_number(a), _to_number(b)
        if first is None or second is None:
            return None
        return [first, second]

    @staticmethod
    def _error(operation: str, message: str) -> str:
        """Return the error payload every operation shares."""
        return json.dumps({"operation": operation, "error": message})

    def add(self, a: float, b: float) -> str:
        """Add two numbers and return the result.

        Args:
            a (float): First number.
            b (float): Second number.

        Returns:
            str: JSON string of the result.
        """
        numbers = self._as_two_numbers(a, b)
        if numbers is None:
            return self._error("addition", "addition requires two numbers")
        a, b = numbers
        result = a + b
        log_debug(f"Adding {a} and {b} to get {result}")
        return json.dumps({"operation": "addition", "result": result})

    def subtract(self, a: float, b: float) -> str:
        """Subtract second number from first and return the result.

        Args:
            a (float): First number.
            b (float): Second number.

        Returns:
            str: JSON string of the result.
        """
        numbers = self._as_two_numbers(a, b)
        if numbers is None:
            return self._error("subtraction", "subtraction requires two numbers")
        a, b = numbers
        result = a - b
        log_debug(f"Subtracting {b} from {a} to get {result}")
        return json.dumps({"operation": "subtraction", "result": result})

    def multiply(self, a: float, b: float) -> str:
        """Multiply two numbers and return the result.

        Args:
            a (float): First number.
            b (float): Second number.

        Returns:
            str: JSON string of the result.
        """
        numbers = self._as_two_numbers(a, b)
        if numbers is None:
            return self._error("multiplication", "multiplication requires two numbers")
        a, b = numbers
        result = a * b
        log_debug(f"Multiplying {a} and {b} to get {result}")
        return json.dumps({"operation": "multiplication", "result": result})

    def divide(self, a: float, b: float) -> str:
        """Divide first number by second and return the result.

        Args:
            a (float): Numerator.
            b (float): Denominator.

        Returns:
            str: JSON string of the result.
        """
        numbers = self._as_two_numbers(a, b)
        if numbers is None:
            return self._error("division", "division requires two numbers")
        a, b = numbers
        if b == 0:
            log_error("Attempt to divide by zero")
            return json.dumps({"operation": "division", "error": "Division by zero is undefined"})
        try:
            result = a / b
        except Exception as e:
            return json.dumps({"operation": "division", "error": str(e), "result": "Error"})
        log_debug(f"Dividing {a} by {b} to get {result}")
        return json.dumps({"operation": "division", "result": result})

    def exponentiate(self, a: float, b: float) -> str:
        """Raise first number to the power of the second number and return the result.

        Args:
            a (float): Base.
            b (float): Exponent.

        Returns:
            str: JSON string of the result.
        """
        numbers = self._as_two_numbers(a, b)
        if numbers is None:
            return self._error("exponentiation", "exponentiation requires two numbers")
        a, b = numbers
        try:
            result = math.pow(a, b)
        except (OverflowError, ValueError) as e:
            log_error(f"Attempt to exponentiate {a} by {b} failed: {e}")
            return self._error("exponentiation", str(e))
        log_debug(f"Raising {a} to the power of {b} to get {result}")
        return json.dumps({"operation": "exponentiation", "result": result})

    def factorial(self, n: int) -> str:
        """Calculate the factorial of a number and return the result.

        Args:
            n (int): Number to calculate the factorial of.

        Returns:
            str: JSON string of the result.
        """
        number = _to_integer(n)
        if number is None:
            return self._error("factorial", "Factorial requires a whole number")
        if number < 0:
            log_error("Attempt to calculate factorial of a negative number")
            return json.dumps({"operation": "factorial", "error": "Factorial of a negative number is undefined"})
        result = math.factorial(number)
        log_debug(f"Calculating factorial of {n} to get {result}")
        return json.dumps({"operation": "factorial", "result": result})

    def is_prime(self, n: int) -> str:
        """Check if a number is prime and return the result.

        Args:
            n (int): Number to check if prime.

        Returns:
            str: JSON string of the result.
        """
        number = _to_integer(n)
        if number is None:
            return self._error("prime_check", "Prime check requires a whole number")
        if number <= 1:
            return json.dumps({"operation": "prime_check", "result": False})
        for i in range(2, int(math.sqrt(number)) + 1):
            if number % i == 0:
                return json.dumps({"operation": "prime_check", "result": False})
        return json.dumps({"operation": "prime_check", "result": True})

    def square_root(self, n: float) -> str:
        """Calculate the square root of a number and return the result.

        Args:
            n (float): Number to calculate the square root of.

        Returns:
            str: JSON string of the result.
        """
        number = _to_number(n)
        if number is None:
            return self._error("square_root", "Square root requires a number")
        if number < 0:
            log_error("Attempt to calculate square root of a negative number")
            return json.dumps({"operation": "square_root", "error": "Square root of a negative number is undefined"})

        result = math.sqrt(number)
        log_debug(f"Calculating square root of {n} to get {result}")
        return json.dumps({"operation": "square_root", "result": result})
