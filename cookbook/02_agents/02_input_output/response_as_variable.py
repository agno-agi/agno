"""
Response As Variable
=============================

Response As Variable.
"""

from typing import Iterator  # noqa
from rich.pretty import pprint
from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[YFinanceTools()],
    instructions=["Use tables where possible"],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_response: RunOutput = agent.run("What is the stock price of NVDA")
    pprint(run_response)

    # run_response_strem: Iterator[RunOutputEvent] = agent.run("What is the stock price of NVDA", stream=True)
    # for response in run_response_strem:
    #     pprint(response)
