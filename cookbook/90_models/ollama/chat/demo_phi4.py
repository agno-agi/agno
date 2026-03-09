"""
Ollama Demo Phi4
================

Cookbook example for `ollama/chat/demo_phi4.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.ollama import Ollama

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Ollama(id="phi4"), markdown=True)

# Print the response in the terminal
agent.print_response("Tell me a scary story in exactly 10 words.")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
