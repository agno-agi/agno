"""
This example shows how to set the debug level of an agent.

The debug level is a number between 1 and 2.

1: Basic debug information
2: Detailed debug information

The default debug level is 1.
"""

from agno.agent.agent import Agent
from agno.models.anthropic.claude import Claude
from agno.tools.yfinance import YFinanceTools

# Basic debug information
agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20240620"),
    tools=[YFinanceTools()],
    debug_mode=True,
    debug_level=1,
)

agent.print_response("What is the current price of Tesla?")

# Verbose debug information
agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20240620"),
    tools=[YFinanceTools()],
    debug_mode=True,
    debug_level=2,
)

agent.print_response("What is the current price of Apple?")
