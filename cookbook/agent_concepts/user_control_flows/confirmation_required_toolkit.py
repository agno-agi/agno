"""🤝 Human-in-the-Loop: Adding User Confirmation to Tool Calls

This example shows how to implement human-in-the-loop functionality in your Agno tools.
It shows how to:
- Handle user confirmation during tool execution
- Gracefully cancel operations based on user choice

Some practical applications:
- Confirming sensitive operations before execution
- Reviewing API calls before they're made
- Validating data transformations
- Approving automated actions in critical systems

Run `pip install openai httpx rich agno` to install dependencies.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool
from agno.tools.yfinance import YFinanceTools
from agno.utils import pprint

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools(requires_confirmation_tools=["get_current_stock_price"])],
    markdown=True,
)

agent.run("What is the current stock price of Apple?")
if agent.is_paused:  # Or agent.run_response.is_paused
    for tool in agent.run_response.tools:
        print("Tool name: ", tool.tool_name)
        print("Tool args: ", tool.tool_args)
        user_input = input("Do you want to proceed? (y/n) ")
        # We update the tools in place
        tool.confirmed = user_input == "y"

    run_response = agent.continue_run()
    pprint.pprint_run_response(run_response)
