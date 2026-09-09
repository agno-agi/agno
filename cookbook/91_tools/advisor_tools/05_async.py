"""
Async Advisors
==============
All advisor tools have async variants. When the agent runs async and calls
`ask_all_advisors`, the advisors are queried in parallel with asyncio.gather,
so the slowest advisor determines the total wait, not the sum of all of them.
"""

import asyncio

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from agno.tools.advisor import AdvisorTools

# ---------------------------------------------------------------------------
# Create Agent with multiple advisors
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        AdvisorTools(
            advisors=[
                Claude(id="claude-sonnet-4-6"),
                Gemini(id="gemini-3.5-flash"),
            ],
        )
    ],
    instructions=[
        "After drafting a response, use ask_all_advisors for feedback from all advisors.",
        "Incorporate the suggestions you agree with into your final answer.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        agent.aprint_response(
            "Explain the CAP theorem and how it applies to distributed databases",
            stream=True,
        )
    )
