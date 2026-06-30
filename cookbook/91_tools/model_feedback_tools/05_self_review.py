"""
Self-Review with Same Provider
===============================
You don't have to use a different provider for feedback. A common pattern is
using a smaller/cheaper model from the same provider as a quick reviewer.

This example uses GPT-4o as the primary agent and GPT-4o-mini as the
reviewer. Benefits:
- Lower cost for the feedback call
- Faster feedback response time
- Still catches many issues (missing context, unclear explanations)

You can also use this pattern to limit conversation context with `max_messages`
to reduce token costs further.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.model_feedback import ModelFeedbackTools

# ---------------------------------------------------------------------------
# Create Agent with same-provider self-review
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            model=OpenAIChat(id="gpt-4o-mini"),
            aspects=["clarity", "completeness", "conciseness"],
            # Only send the last 10 messages to the reviewer to save tokens
            max_messages=10,
        )
    ],
    instructions=[
        "After drafting a response, use get_feedback for a quick self-review.",
        "Focus on the clarity and conciseness suggestions.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Explain the CAP theorem and how it applies to distributed databases",
        stream=True,
    )
