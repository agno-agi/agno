"""
Court Rules Tools
=============================

Demonstrates CourtRulesTools for looking up U.S. court filing rules, judge standing
orders and court holidays before a document is filed.

Requirements:
- A Court Rules API key. Sign in at https://console.courtrules.app (Google or email)
  to create one. API docs: https://docs.courtrules.app

Set the following environment variable (or pass the key to CourtRulesTools):

    export COURT_RULES_API_KEY="your_api_key"
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.court_rules import CourtRulesTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Every tool has its own enable_* flag, so you can expose only what the agent needs:
#   CourtRulesTools(enable_list_court_holidays=False)
#   CourtRulesTools(all=True)  # register every tool
agent = Agent(
    name="Court Filing Rules Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[CourtRulesTools()],
    instructions=[
        "Look up the court and judge with the tools before answering, and never guess a rule.",
        "Quote the rule, cite its source_url, and say when a court or judge has no rules loaded.",
        "Remind the user to confirm the rule against the court's official document before filing.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What page limits and pre-motion conference rules apply to a summary judgment "
        "brief before Judge Nicholas G. Garaufis in the Eastern District of New York?",
        stream=True,
    )

    agent.print_response(
        "Which days is the Eastern District of New York closed in 2026?",
        stream=True,
    )

    # Async usage
    asyncio.run(
        agent.aprint_response(
            "What courtesy copy rules apply in the Superior Court of California, County of Los Angeles?",
            stream=True,
        )
    )
