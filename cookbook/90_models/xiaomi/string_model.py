"""
Xiaomi MiMo String Model
========================

Create a MiMo agent without importing the model class, using the
`model="xiaomi:<model-id>"` string shorthand.
"""

from agno.agent import Agent

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model="xiaomi:mimo-v2.5-pro", markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Explain why tool-calling agents need conversation history.",
        stream=True,
    )
