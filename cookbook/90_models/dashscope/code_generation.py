"""Code generation examples using Qwen-Coder models"""

from agno.agent import Agent
from agno.models.dashscope import DashScope

# IMPORTANTE: Use o nome EXATO que aparece no LM Studio
# Para código: "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF" ou nome simplificado no LM Studio
MODEL_ID = "qwen2.5-coder-3b-instruct"
BASE_URL = "http://localhost:1234/v1"


def example_basic_code_generation():
    """Basic code generation with Qwen"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    agent.print_response(
        "Write a Python function to calculate fibonacci numbers using memoization"
    )


def example_code_explanation():
    """Code explanation and documentation"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    code = """
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)
"""

    agent.print_response(f"Explain this code and add detailed docstrings:\n\n{code}")


def example_code_refactoring():
    """Code refactoring and optimization"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    code = """
def process_data(data):
    result = []
    for i in range(len(data)):
        if data[i] > 0:
            result.append(data[i] * 2)
    return result
"""

    agent.print_response(
        f"Refactor this code to be more Pythonic and efficient:\n\n{code}"
    )


def example_bug_fixing():
    """Bug detection and fixing"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    buggy_code = """
def calculate_average(numbers):
    total = 0
    for num in numbers:
        total += num
    return total / len(numbers)

result = calculate_average([])
"""

    agent.print_response(f"Find and fix bugs in this code:\n\n{buggy_code}")


def example_code_completion():
    """Code completion and suggestions"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    partial_code = """
class BinaryTree:
    def __init__(self, value):
        self.value = value
        self.left = None
        self.right = None

    def insert(self, value):
        # TODO: Complete this method
"""

    agent.print_response(
        f"Complete the insert method for this binary tree:\n\n{partial_code}"
    )


def example_test_generation():
    """Unit test generation"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    code = """
def validate_email(email):
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None
"""

    agent.print_response(
        f"Generate comprehensive pytest unit tests for this function:\n\n{code}"
    )


def example_multi_language():
    """Code generation in different languages"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    agent.print_response("Write a function to reverse a linked list in JavaScript")


def example_algorithm_implementation():
    """Complex algorithm implementation"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    agent.print_response(
        "Implement Dijkstra's shortest path algorithm in Python with detailed comments"
    )


def example_lru_cache():
    """LRU cache implementation"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    agent.print_response("Write a Python class for a LRU cache with O(1) operations")


def example_api_endpoint():
    """API endpoint creation"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    agent.print_response("Create a FastAPI endpoint for user authentication with JWT")


if __name__ == "__main__":
    print("\n=== Example 1: Basic Code Generation ===")
    example_basic_code_generation()

    print("\n=== Example 2: Code Explanation ===")
    example_code_explanation()

    print("\n=== Example 3: Code Refactoring ===")
    example_code_refactoring()
