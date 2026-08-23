"""
Agno Gateway - reasoning effort
===============================

Pass ``reasoning_effort`` to a reasoning model. The gateway forwards it to the
provider, and any returned reasoning content is surfaced on the response.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

from agno.agent import Agent
from agno.models.agno import Agno

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Agno(id="openai/gpt-5.4", reasoning_effort="high"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "A train leaves at 3pm going 60mph, another at 4pm going 80mph on the same "
        "track. When does the second catch the first? Explain your reasoning."
    )
