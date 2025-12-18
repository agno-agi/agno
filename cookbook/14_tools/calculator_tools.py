from agno.agent import Agent
from agno.tools.calculator import CalculatorTools

# Example 1: Include specific calculator functions for basic operations
basic_calc_agent = Agent(
    tools=[CalculatorTools(include_tools=["add", "subtract", "multiply", "divide"])],
    markdown=True,
)

# Example 2: Exclude advanced functions for simple use cases
simple_calc_agent = Agent(
    tools=[CalculatorTools(exclude_tools=["factorial", "is_prime", "exponentiate"])],
    markdown=True,
)

# Example 3: Full calculator functionality (default)
agent = Agent(
    tools=[CalculatorTools()],
    markdown=True,
)
simple_calc_agent.print_response(
    "What is 10*5 then to the power of 2, do it step by step"
)
