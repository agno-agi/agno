"""
Sarvam String Model
===================

Create a Sarvam agent without importing the model class, using the
`model="sarvam:<model-id>"` string shorthand. `gemma4` is used here because it
does not reason by default, so the example stays fast.
"""

from agno.agent import Agent

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model="sarvam:gemma4", markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Explain why tool-calling agents need conversation history.",
        stream=True,
    )
