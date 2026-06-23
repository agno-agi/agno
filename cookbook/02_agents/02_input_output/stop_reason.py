"""
Stop Reason
=============================

Demonstrates the stop_reason field which tells you why the model stopped generating.

When max_tokens is reached, Agno automatically logs a warning:
  WARNING  Model 'claude-sonnet-4-20250514' response truncated: max_tokens limit reached.

Possible stop_reason values (Claude):
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
    agent.print_response("Write a detailed essay about climate change.")
