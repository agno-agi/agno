"""
4. Gemini Native Search
=======================
Use Gemini's built-in Google Search integration.
Unlike external tools, this is a native model capability --
no extra dependencies, just set search=True.

Run:
    python cookbook/gemini_3/4_search.py

Example prompt:
    "What are the latest developments in AI this week?"
"""

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
news_agent = Agent(
    name="News Agent",
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions="You are a news analyst. Summarize the latest developments clearly and concisely.",
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    news_agent.print_response(
        "What are the latest developments in AI this week?",
        stream=True,
    )
