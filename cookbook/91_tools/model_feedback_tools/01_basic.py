"""
Basic Model Feedback
====================
The simplest usage of ModelFeedbackTools: attach a single feedback model
to your agent. The agent can call `get_feedback` at any point to get a
structured critique of its response from the secondary model.

How it works:
1. The primary agent (OpenAI) drafts a response
2. It calls `get_feedback` which sends the conversation to Gemini
3. Gemini returns structured JSON with ratings and suggestions
4. The primary agent incorporates the feedback into its final answer

The feedback model evaluates three default aspects:
- accuracy: Are the facts correct?
- completeness: Does the response fully address the question?
- clarity: Is the response well-structured and easy to understand?
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.model_feedback import ModelFeedbackTools

# ---------------------------------------------------------------------------
# Create Agent with a Gemini feedback model
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            model=Gemini(id="gemini-2.0-flash"),
        )
    ],
    instructions=[
        "After drafting a response, use the get_feedback tool to get a second opinion.",
        "Review the feedback and incorporate relevant suggestions.",
        "Then provide your final, improved answer.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Explain how DNS resolution works when you type a URL in your browser",
        stream=True,
    )
