"""
Gemini Interactions - Deep Research with Visualization
=======================================================

With `visualization="auto"` the agent can generate charts and graphs to
support its findings. The capability is enabled by the config, but the
agent only produces visuals when the prompt explicitly asks for them.

Generated images come back in the response steps (and as image deltas when
streaming). Agno parses them into the response's images.
"""

from agno.agent import Agent
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(
        agent="deep-research-preview-04-2026",
        thinking_summaries="auto",
        visualization="auto",
    ),
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Analyze global semiconductor market trends. Include graphics showing "
        "market share changes over time."
    )
