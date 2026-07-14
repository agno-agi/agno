"""
Openai Chat Citations
=====================

Cookbook example for `openai/chat/citations.py`.

OpenAI web-search chat models return
`url_citation` annotations alongside the content. Agno surfaces these on
`response.citations`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# `gpt-4o-search-preview` performs a web search and attaches url_citation
# annotations to the response.
agent = Agent(model=OpenAIChat(id="gpt-4o-search-preview"), markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What are the latest developments in AI? Cite your sources.")
