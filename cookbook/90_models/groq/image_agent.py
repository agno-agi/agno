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

# reasoning_effort="none" disables qwen's thinking tokens: over Groq they
# stream as raw <think> text and the answer can cut off before it appears.
agent = Agent(
    model=Groq(id="qwen/qwen3.6-27b", request_params={"reasoning_effort": "none"})
)

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
