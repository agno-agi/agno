"""
iFLYTEK Spark String Model
==========================

Create a Spark agent without importing the model class, using the
`model="spark:<model-id>"` string shorthand.
"""

from agno.agent import Agent

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model="spark:4.0Ultra", markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Explain why tool-calling agents need conversation history.",
        stream=True,
    )
