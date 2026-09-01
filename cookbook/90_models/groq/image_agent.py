"""
Groq Image Agent
================

Cookbook example for `groq/image_agent.py`.
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.groq import Groq

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Groq(id="qwen/qwen3.6-27b"))

agent.print_response(
    "Tell me about this image",
    images=[
        Image(url="https://agno-public.s3.amazonaws.com/images/krakow_mariacki.jpg"),
    ],
    stream=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
