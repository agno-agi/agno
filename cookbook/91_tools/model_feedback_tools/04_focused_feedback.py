"""
Focused Feedback with the `focus` Parameter
=============================================
The `get_feedback` tool accepts an optional `focus` parameter that lets the
agent direct the reviewer's attention to a specific area. This is useful when
the agent knows which part of its response might need the most scrutiny.

For example:
- "check the code example for bugs"
- "verify the historical dates"
- "evaluate whether the tone is appropriate for a child"

The `focus` gets injected into the system prompt as:
"Pay special attention to: <focus>"
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.model_feedback import ModelFeedbackTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            model=Gemini(id="gemini-2.0-flash"),
            aspects=["accuracy", "code_correctness", "completeness"],
        )
    ],
    instructions=[
        "You are a helpful programming assistant.",
        "When your response includes code, use the get_feedback tool with "
        'focus="check the code for correctness and edge cases".',
        "When your response is purely conceptual, use get_feedback with "
        'focus="verify technical accuracy".',
        "Incorporate the feedback before giving your final answer.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # This prompt should trigger code-focused feedback
    agent.print_response(
        "Write a Python function to find all prime numbers up to N using the Sieve of Eratosthenes",
        stream=True,
    )
