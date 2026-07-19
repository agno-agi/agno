"""
Ollama Image Agent
==================

Cookbook example for `ollama/chat/image_agent.py`.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.ollama import Ollama

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Ollama(id="llama3.2-vision"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("super-agents.png")
agent.print_response(
    "Write a 3 sentence fiction story about the image",
    images=[Image(filepath=image_path)],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
