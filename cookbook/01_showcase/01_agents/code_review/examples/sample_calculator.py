"""
Sample Calculator App with Bugs
===============================

This file contains intentional bugs for testing the Code Review Agent.
"""

import os

# Hardcoded credentials (security issue)
DB_PASSWORD = "admin123"
API_KEY = "sk-1234567890abcdef"

class Calculator:
    def __init__(self):
        self.history = []
        self.result = 0
    
    def add(self, a, b):
        # Missing type validation
        result = a + b
        self.history.append(f"{a} + {b} = {result}")
        return result
    
    def subtract(self, a, b):
        result = a - b
        self.history.append(f"{a} - {b} = {result}")
        return result
    
    def multiply(self, a, b):
        result = a * b
        self.history.append(f"{a} * {b} = {result}")
        return result
    
    def divide(self, a, b):
        # Bug: No check for division by zero
        result = a / b
        self.history.append(f"{a} / {b} = {result}")
        return result
    
    def power(self, base, exp):
        # Bug: Infinite loop for negative exponents
        result = 1
        for i in range(exp):
            result *= base
        return result
    
    def sqrt(self, n):
        # Bug: No check for negative numbers
        return n ** 0.5
    
    def factorial(self, n):
        # Bug: No base case for recursion, will cause stack overflow
        # Bug: No check for negative numbers
        return n * self.factorial(n - 1)
    
    def get_history(self):
        return self.history
    
    def clear_history(self):
        self.history = []


def calculate_from_input(expression):
    # Security issue: Using eval on user input
    result = eval(expression)
    return result


def save_history_to_file(history, filename):
    # Bug: File handle not closed properly (resource leak)
    f = open(filename, 'w')
    for item in history:
        f.write(item + '\n')
    # Missing f.close()


def load_history_from_file(filename):
    # Bug: No error handling for missing file
    f = open(filename, 'r')
    history = f.readlines()
    f.close()
    return history


def calculate_average(numbers):
    # Bug: No check for empty list (division by zero)
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)


def find_max(numbers):
    # Bug: Off-by-one error in loop
    max_val = numbers[0]
    for i in range(1, len(numbers) + 1):
        if numbers[i] > max_val:
            max_val = numbers[i]
    return max_val


def process_calculation(user_id, operation):
    # SQL Injection vulnerability
    query = f"INSERT INTO calculations (user_id, operation) VALUES ({user_id}, '{operation}')"
    # db.execute(query)
    return query


def log_calculation(calc_type, values, result):
    # Bug: Logging sensitive data
    print(f"User performed {calc_type} with password {DB_PASSWORD}")
    print(f"API Key used: {API_KEY}")
    print(f"Values: {values}, Result: {result}")


class AdvancedCalculator(Calculator):
    def __init__(self):
        # Bug: Missing super().__init__() call
        self.memory = 0
    
    def memory_add(self, value):
        self.memory += value
    
    def memory_recall(self):
        return self.memory
    
    def memory_clear(self):
        self.memory = 0
    
    def percentage(self, value, percent):
        # Bug: Incorrect calculation (missing division by 100)
        return value * percent
    
    def modulo(self, a, b):
        # Bug: No check for modulo by zero
        return a % b


# Global mutable default argument (bug)
def batch_calculate(operations, results=[]):
    for op in operations:
        results.append(eval(op))
    return results


def validate_number(value):
    # Bug: Incorrect validation logic
    if value is not None or value != "":
        return True
    return False


# Unused variable (code smell)
UNUSED_CONSTANT = 42


if __name__ == "__main__":
    calc = Calculator()
    
    # These will cause errors
    print(calc.divide(10, 0))  # Division by zero
    print(calc.factorial(-5))  # Negative factorial
    print(calculate_average([]))  # Empty list average
