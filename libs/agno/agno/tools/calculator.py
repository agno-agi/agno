import json
import math
from typing import Callable, List

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class CalculatorTools(Toolkit):
    """Toolkit for basic mathematical operations.

    Args:
        add: Enable add tool. Defaults to True.
        subtract: Enable subtract tool. Defaults to True.
        multiply: Enable multiply tool. Defaults to True.
        divide: Enable divide tool. Defaults to True.
        exponentiate: Enable exponentiate tool. Defaults to True.
        factorial: Enable factorial tool. Defaults to True.
        is_prime: Enable is_prime tool. Defaults to True.
        square_root: Enable square_root tool. Defaults to True.
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        add: bool = True,
        subtract: bool = True,
        multiply: bool = True,
        divide: bool = True,
        exponentiate: bool = True,
        factorial: bool = True,
        is_prime: bool = True,
        square_root: bool = True,
        all: bool = False,
        **kwargs,
    ):
        tools: List[Callable] = []
        if all or add:
            tools.append(self.add)
        if all or subtract:
            tools.append(self.subtract)
        if all or multiply:
            tools.append(self.multiply)
        if all or divide:
            tools.append(self.divide)
        if all or exponentiate:
            tools.append(self.exponentiate)
        if all or factorial:
            tools.append(self.factorial)
        if all or is_prime:
            tools.append(self.is_prime)
        if all or square_root:
            tools.append(self.square_root)

        super().__init__(name="calculator", tools=tools, **kwargs)

    def add(self, a: float, b: float) -> str:
        """Add two numbers and return the result.

        Args:
            a: First number.
            b: Second number.

        Returns:
            JSON with the result.
        """
        result = a + b
        log_debug(f"Adding {a} and {b} to get {result}")
        return json.dumps({"operation": "addition", "result": result})

    def subtract(self, a: float, b: float) -> str:
        """Subtract second number from first and return the result.

        Args:
            a: First number.
            b: Second number.

        Returns:
            JSON with the result.
        """
        result = a - b
        log_debug(f"Subtracting {b} from {a} to get {result}")
        return json.dumps({"operation": "subtraction", "result": result})

    def multiply(self, a: float, b: float) -> str:
        """Multiply two numbers and return the result.

        Args:
            a: First number.
            b: Second number.

        Returns:
            JSON with the result.
        """
        result = a * b
        log_debug(f"Multiplying {a} and {b} to get {result}")
        return json.dumps({"operation": "multiplication", "result": result})

    def divide(self, a: float, b: float) -> str:
        """Divide first number by second and return the result.

        Args:
            a: Numerator.
            b: Denominator.

        Returns:
            JSON with the result.
        """
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
        """Raise first number to the power of the second and return the result.

        Args:
            a: Base.
            b: Exponent.

        Returns:
            JSON with the result.
        """
        result = math.pow(a, b)
        log_debug(f"Raising {a} to the power of {b} to get {result}")
        return json.dumps({"operation": "exponentiation", "result": result})

    def factorial(self, n: int) -> str:
        """Calculate the factorial of a number and return the result.

        Args:
            n: Number to calculate the factorial of.

        Returns:
            JSON with the result.
        """
        if n < 0:
            log_error("Attempt to calculate factorial of a negative number")
            return json.dumps({"operation": "factorial", "error": "Factorial of a negative number is undefined"})
        result = math.factorial(n)
        log_debug(f"Calculating factorial of {n} to get {result}")
        return json.dumps({"operation": "factorial", "result": result})

    def is_prime(self, n: int) -> str:
        """Check if a number is prime and return the result.

        Args:
            n: Number to check.

        Returns:
            JSON with the result.
        """
        if n <= 1:
            return json.dumps({"operation": "prime_check", "result": False})
        for i in range(2, int(math.sqrt(n)) + 1):
            if n % i == 0:
                return json.dumps({"operation": "prime_check", "result": False})
        return json.dumps({"operation": "prime_check", "result": True})

    def square_root(self, n: float) -> str:
        """Calculate the square root of a number and return the result.

        Args:
            n: Number to calculate the square root of.

        Returns:
            JSON with the result.
        """
        if n < 0:
            log_error("Attempt to calculate square root of a negative number")
            return json.dumps({"operation": "square_root", "error": "Square root of a negative number is undefined"})

        result = math.sqrt(n)
        log_debug(f"Calculating square root of {n} to get {result}")
        return json.dumps({"operation": "square_root", "result": result})
