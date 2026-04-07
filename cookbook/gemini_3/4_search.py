"""
Gemini Native Search - Real-Time News Agent
=============================================
Use Gemini's built-in Google Search. Just set search=True on the model.

Key concepts:
- search=True: Enables native Google Search on the Gemini model
- No extra dependencies: Unlike WebSearchTools (step 2), nothing to install
- Native search is seamless but less controllable than tool-based search

Example prompts to try:
- "What are the latest developments in AI this week?"
- "What happened in the stock market today?"
- "What are the top trending tech stories right now?"
"""

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a news analyst. Summarize the latest developments clearly and concisely.

## Rules

- Lead with the most important story
- Include dates for all events
- Cite sources when possible
- Use bullet points for multiple items\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
news_agent = Agent(
    name="News Agent",
    # search=True enables Gemini's native Google Search, no extra tools needed
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions=instructions,
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

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Native search vs tool-based search:

1. Native search (this example)
   model=Gemini(id="gemini-3-flash-preview", search=True)
   - Seamless: model decides when to search
   - Less controllable: you can't see individual search calls
   - No extra packages needed

2. Tool-based search (step 2)
   tools=[WebSearchTools()]
   - Explicit: agent calls search as a tool
   - More controllable: you can see search queries in tool calls
   - Works with any model, not just Gemini

3. Grounding (step 5)
   model=Gemini(id="...", grounding=True)
   - Fact-based: responses include citations
   - Verifiable: grounding metadata shows sources
   - Best for factual accuracy

Choose based on your needs:
- Quick current info → Native search
- Full control over search → Tool-based
- Cited, verifiable facts → Grounding
"""
