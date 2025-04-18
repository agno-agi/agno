from rich.pretty import pprint
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools
import sys

# Option 1: Using sys.getsizeof() for basic size
# Option 2: Using objsize for more accurate size (install with pip install objsize)
try:
    import objsize
    has_objsize = True
except ImportError:
    has_objsize = False

agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions="Use tables to display data.",
    markdown=True,
)

if __name__ == "__main__":
    response = agent.print_response(
        "NVDA stock price?",
        stream=True,
        show_full_reasoning=True,
        stream_intermediate_steps=True,
    )

    # Print the original response
    pprint(agent.run_response)

    # Display the size of the run_response object
    print(f"\nBasic size of run_response: {sys.getsizeof(agent.run_response)} bytes")

    # If objsize is available, get a more accurate size measurement
    if has_objsize:
        total_size = objsize.get_deep_size(agent.run_response)
        print(f"Total deep size of run_response: {total_size} bytes ({total_size/1024:.2f} KB)")

    # If you want to check the size of the entire agent.run object
    if hasattr(agent, "run"):
        print(f"\nBasic size of agent.run: {sys.getsizeof(agent.run)} bytes")
        if has_objsize:
            run_total_size = objsize.get_deep_size(agent.run)
            print(f"Total deep size of agent.run: {run_total_size} bytes ({run_total_size/1024:.2f} KB)")