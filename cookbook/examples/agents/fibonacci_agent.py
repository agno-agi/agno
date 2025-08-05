import json

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

def get_fibonacci_series(count: int = 5) -> str:
    """Generate a Fibonacci series up to the specified count."""
    if count <= 0:
        return "Count must be a positive integer."

    fib_series = [0, 1]
    for i in range(2, count):
        fib_series.append(fib_series[-1] + fib_series[-2])

    return json.dumps(fib_series[:count])

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        get_fibonacci_series,
        CalculatorTools(
            add=True,
            subtract=True,
            exponentiate=True,
            is_prime=True
        )
    ],
    show_tool_calls=True,
    markdown=True
)

agent.print_response("""
    1. Get 10 elements of fibonacci series
    2. Calculate the sum of cubes of the prime numbers in the series
    3. Subtract 4
""", stream=True)
