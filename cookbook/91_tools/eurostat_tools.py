"""
Eurostat Tools - Live European Union official statistics

This example shows how to use EurostatTools to answer questions about the EU
economy and population with real, published figures from Eurostat (the EU's
statistical office) instead of letting the language model guess or recall
stale training data.

No API key or registration is required -- Eurostat's dissemination API is
fully public.

Note:
- Eurostat dataset codes are terse (e.g. "une_rt_m"). `get_indicator` covers
  a handful of common ones (unemployment_rate, inflation_rate, gdp,
  population) under friendly names; use `get_dataset` with a raw code from
  https://ec.europa.eu/eurostat/databrowser for anything else.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.eurostat import EurostatTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[EurostatTools()],
    instructions=[
        "Use the Eurostat tools to answer questions about EU statistics with real data.",
        "Never estimate or recall economic figures from memory, always call a tool.",
        "Cite the time period each figure applies to.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Unemployment rate ===")
    agent.print_response(
        "What is Germany's most recent monthly unemployment rate?",
        stream=True,
    )

    print("\n=== Inflation ===")
    agent.print_response(
        "What has France's HICP inflation rate been since the start of 2026?",
        stream=True,
    )

    print("\n=== GDP ===")
    agent.print_response(
        "Compare Germany's and Italy's GDP for the most recent year available.",
        stream=True,
    )

    print("\n=== Raw dataset lookup ===")
    agent.print_response(
        "Using the raw Eurostat dataset 'demo_pjan', what was the Netherlands' "
        "total population on 1 January, for each year since 2020?",
        stream=True,
    )
