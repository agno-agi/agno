"""
Market Brief with FinanceTools
==============================
The simplest finance agent: one toolkit, no API key.

`FinanceTools()` defaults to the Yahoo Finance provider (via `yfinance`) and
registers the seven "market brief" tools: search_symbols, get_quote,
get_price_history, get_company_profile, get_key_metrics, get_news and
get_analyst_recommendations. Every tool returns the same JSON shape no matter
which provider is behind it, so the agent code never changes when you swap
providers (see 03_swap_provider.py).

Prompts to try:
- "Give me a market brief on NVIDIA"
- "How has AMD traded over the last 3 months?"
- "What do analysts think about Tesla right now?"

Run: pip install yfinance
"""

from agno.agent import Agent
from agno.tools.finance import FinanceTools

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Finance Agent",
    model="openai:gpt-5.6",
    tools=[FinanceTools()],
    instructions="Lead with the answer, then show the evidence.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Give me a market brief on NVIDIA", stream=True)
