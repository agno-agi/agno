"""Google Search with Gemini.

The search tool enables Gemini to access current information from Google Search.
This is useful for getting up-to-date facts, news, and web content.

Run `uv pip install google-generativeai` to install dependencies.
"""

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-3-flash-preview", search=True),
    markdown=True,
)

# Ask questions that require current information

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What are the latest developments in AI technology this week?")
