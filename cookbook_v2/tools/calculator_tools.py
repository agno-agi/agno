from agno.agent import Agent
from agno.tools.calculator import CalculatorTools

agent = Agent(
    tools=[
        CalculatorTools(
            add=True,
            subtract=True,
            multiply=True,
            divide=True,
            exponentiate=True,
            factorial=True,
            is_prime=True,
            square_root=True,
        )
    ],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("What is 10*5 then to the power of 2, do it step by step")
