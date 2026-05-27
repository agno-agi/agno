"""
Ollama Demo Deepseek R1
=======================

Cookbook example for `ollama/chat/demo_deepseek_r1.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.ollama import Ollama

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Ollama(id="deepseek-r1:14b"), markdown=True)

# Print the response in the terminal
agent.print_response(
    "Write me python code to solve quadratic equations. Explain your reasoning."
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
