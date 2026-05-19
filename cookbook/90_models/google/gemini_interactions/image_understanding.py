"""
Gemini Interactions - Image Understanding
==========================================

Example showing image understanding with the Interactions API.
Supports images from URLs, local files, and raw bytes.
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(id="gemini-3-flash-preview"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Image from URL ---
    agent.print_response(
        "What do you see in this image? Describe it in detail.",
        images=[Image(url="https://picsum.photos/id/237/400/300")],
    )
