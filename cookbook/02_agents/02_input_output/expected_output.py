"""
Expected Output
=============================

Guide agent responses using the expected_output parameter.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    # expected_output gives the agent a clear target for what the response should look like
    expected_output="A numbered list of exactly 5 items, each with a title and one-sentence description.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What are the most important principles of clean code?",
        stream=True,
    )
