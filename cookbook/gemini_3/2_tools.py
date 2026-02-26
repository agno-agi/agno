"""
Agent with Tools - Finance Research Agent
==========================================
Give an agent tools to search the web and take real-world actions.

Key concepts:
- tools: A list of Toolkit instances the agent can call
- instructions: System-level guidance that shapes the agent's behavior
- add_datetime_to_context: Injects the current date/time so the agent knows "today"
- WebSearchTools: Built-in toolkit for web search via DuckDuckGo (no API key needed)

Example prompts to try:
- "Compare the latest funding rounds in AI startups this month"
- "What's happening with interest rates this week?"
- "Find the latest news about Nvidia's earnings"
- "What are the top tech IPOs planned for this quarter?"
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a finance research agent. You find and analyze current financial news.

## Workflow

1. Search the web for the requested financial information
2. Analyze and compare findings
3. Present a clear, structured summary

## Rules

- Always cite your sources
- Use tables for comparisons
- Include dates for all data points\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
finance_agent = Agent(
    name="Finance Agent",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[WebSearchTools()],
    # Adds current date/time to the system message so the agent knows "today"
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    finance_agent.print_response(
        "Compare the latest funding rounds in AI startups this month",
        stream=True,
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Tools are Python classes that inherit from Toolkit. Agno includes many built-in:

1. Web search (no API key needed)
   from agno.tools.websearch import WebSearchTools
   tools=[WebSearchTools()]

2. Yahoo Finance (real market data)
   from agno.tools.yfinance import YFinanceTools
   tools=[YFinanceTools(all=True)]

3. Exa search (semantic search, needs EXA_API_KEY)
   from agno.tools.exa import ExaTools
   tools=[ExaTools()]

4. Custom tools
   @tool
   def my_tool(query: str) -> str:
       return "result"

You can combine multiple toolkits:
   tools=[WebSearchTools(), YFinanceTools(all=True)]

The agent decides which tool to call based on the prompt.
"""
