"""
Agno Gateway - image input
==========================

Send an image alongside the prompt. The class encodes images into the OpenAI
chat-completions content schema, which the gateway forwards to the provider. Use a
vision-capable model.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.agno import Agno

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What is this an image of? Describe it in two sentences.",
        images=[
            Image(
                url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
            )
        ],
    )
