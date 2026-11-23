"""
Agent with Tools - Your First Useful Agent
===========================================
Start here. This example combines the three pieces of an Agno agent:

1. A model that reasons about the request
2. Instructions that define good work
3. Tools that let the agent act on live data

The agent uses Yahoo Finance to turn a plain-English question into tool calls
and a current market brief.

Example prompts to try:
- "What's the current price of AAPL?"
- "Compare NVDA and AMD"
- "Give me a quick market brief on Microsoft"
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent_with_tools = Agent(
    name="Agent with Tools",
    model=Gemini(id="gemini-3.6-flash"),
    instructions=[
        "Use Yahoo Finance for facts that can change.",
        "Lead with the answer, then show the evidence.",
        "Use a table when comparing companies.",
        "Say when data is unavailable; never invent a value.",
        "Keep the response concise and do not give personalized financial advice.",
    ],
    tools=[
        YFinanceTools(
            enable_company_info=True,
            enable_stock_fundamentals=True,
            enable_company_news=True,
        )
    ],
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_with_tools.print_response(
        "Give me a quick market brief on NVIDIA",
        stream=True,
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Swap the prompt and run the file again:

- Single company: "What is Apple's current valuation?"
- Comparison: "Compare Google and Microsoft"
- Sector: "Show key metrics for NVDA, AMD, GOOGL, and MSFT"

The same Agent object can be reused for every request. Do not create agents
inside a loop.
"""
