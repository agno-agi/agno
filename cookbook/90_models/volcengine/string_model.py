"""
Volcengine Ark String Model
===========================

Create an Ark agent without importing the model class, using the
`model="volcengine:<model-id>"` string shorthand.
"""

from agno.agent import Agent

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model="volcengine:doubao-seed-2-1-pro-260628", markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Explain why tool-calling agents need conversation history.",
        stream=True,
    )
