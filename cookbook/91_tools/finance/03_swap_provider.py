"""
Swap the Provider, Keep the Agent
=================================
The point of FinanceTools: the agent is written once against a fixed tool
surface, and the data provider is a configuration choice.

Three ways to pick a provider:
1. `FinanceTools()`                                 -> YFinance() (default, no key)
2. `FinanceTools(provider=FinancialDatasets())`     -> a provider instance (recommended)
3. `FinanceTools(provider="financial_datasets")`    -> registered id, for env/config-driven setups

This example builds the same agent for each configured provider and runs the
same prompt, so you can compare answers side by side.

Run:
    python cookbook/91_tools/finance/03_swap_provider.py            # yfinance only
    FINANCIAL_DATASETS_API_KEY=... python cookbook/91_tools/finance/03_swap_provider.py
"""

from os import getenv

from agno.agent import Agent
from agno.tools.finance import FinanceTools
from agno.tools.finance.providers import FinancialDatasets, YFinance

# ---------------------------------------------------------------------------
# Providers to compare (financialdatasets.ai only when a key is present)
# ---------------------------------------------------------------------------
providers = [YFinance()]
if getenv("FINANCIAL_DATASETS_API_KEY"):
    providers.append(FinancialDatasets())

INSTRUCTIONS = [
    "Lead with the answer, then show the evidence.",
    "State the ticker, currency and the as-of time of the data you used.",
]

# ---------------------------------------------------------------------------
# Create one agent per provider - the agent code is identical
# ---------------------------------------------------------------------------
agents = [
    Agent(
        name=f"Finance Agent ({provider.id})",
        model="openai:gpt-5.6",
        tools=[FinanceTools(provider=provider)],
        instructions=INSTRUCTIONS,
        markdown=True,
    )
    for provider in providers
]

# ---------------------------------------------------------------------------
# Run the same prompt through each
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for provider, agent in zip(providers, agents):
        print(f"\n===== {provider.name} | status: {provider.status()} =====\n")
        agent.print_response(
            "What is Apple's current price, P/E and market cap?", stream=True
        )
