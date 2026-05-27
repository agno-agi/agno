"""
Xiaomi MiMo String Model
========================

Cookbook example for using `xiaomi:<model-id>` string syntax.
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
