"""
Perplexity Web Search
=====================

Cookbook example for `perplexity/web_search.py`.
"""

import os

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(
        id="openai/gpt-5.6-luna",
        base_url="https://api.perplexity.ai/v1",
        api_key=os.environ["PERPLEXITY_API_KEY"],
        extra_body={"preset": "medium"},
    ),
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Show me top 2 news stories from USA?")

# Get the response in a variable
# run: RunOutput = agent.run("What is happening in the world today?")
# print(run.content)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
