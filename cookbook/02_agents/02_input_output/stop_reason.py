"""
Stop Reason
=============================

Demonstrates how to check stop_reason to understand why the model stopped generating.

stop_reason tells you WHY the model stopped:
- "end_turn": Normal completion
- "max_tokens": Hit the output token limit (response may be truncated)
- "tool_use": Model wants to call a tool
- "stop_sequence": Hit a custom stop sequence
- "refusal": Model refused to respond
"""

from agno.agent import Agent
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent with low max_tokens to trigger truncation
# ---------------------------------------------------------------------------
agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = agent.run("Write a detailed essay about climate change.")

    print(f"Content: {response.content}")
    print(f"Stop reason: {response.stop_reason}")

    if response.stop_reason == "max_tokens":
        print("\nWarning: Response was truncated due to max_tokens limit.")
