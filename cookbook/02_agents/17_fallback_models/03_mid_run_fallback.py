"""
Fallback Models — Mid-Run Failure
====================================

Tests what happens when the primary model fails AFTER a tool call (and or within a run).

Flow:
  1. gpt-4o receives the request and makes a tool call
  2. The tool mutates the model instance's id to something invalid
  3. The next API call inside Model.response()'s while-loop fails
  4. The error bubbles up to call_model_with_fallback
  5. Fallback (Claude) is tried
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat


def break_model(agent: Agent) -> str:
    """Tool that corrupts the executing model's id mid-run."""
    # Mutate the actual model instance so the next API call in the
    # response() loop hits an invalid model id.
    agent.model.id = "gpt-4o-invalid"  # type: ignore[union-attr]
    return "Tool executed successfully."


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[break_model],
    fallback_models=[Claude(id="claude-sonnet-4-20250514")],
)

if __name__ == "__main__":
    agent.print_response("Call the break_model tool", stream=True)
