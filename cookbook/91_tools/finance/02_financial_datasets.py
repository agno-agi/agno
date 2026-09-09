"""
FinanceTools with financialdatasets.ai
======================================
Same agent as 01_market_brief.py, different data provider.

financialdatasets.ai is a structured, real-time market data API built for
agents (statements, metrics, filings, insider trades, news). Swap it in with
`provider=FinancialDatasets()` (or the shorthand `provider="financial_datasets"`);
the tool names and JSON shapes the agent sees do not change.

The provider does not offer symbol search or analyst consensus, so those two
tools are simply not registered. Everything else is served from the API.

Setup:
    export FINANCIAL_DATASETS_API_KEY=...   # requests cost credits: https://financialdatasets.ai/pricing
"""

from agno.agent import Agent
from agno.tools.finance import FinanceTools
from agno.tools.finance.providers import FinancialDatasets

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
finance_tools = FinanceTools(provider=FinancialDatasets(), all=True)

agent = Agent(
    name="Finance Agent",
    model="openai:gpt-5.6",
    tools=[finance_tools],
    instructions="Lead with the answer, then show the evidence. Cite the reporting period for any statement figures.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Provider status:", finance_tools.status())
    print("Registered tools:", finance_tools.registered_tools)
    agent.print_response(
        "Give me a market brief on NVIDIA, including last quarter's revenue and net margin.",
        stream=True,
    )
