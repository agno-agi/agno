"""
Gemini Interactions - Audio Understanding
==========================================

Example showing audio understanding with the Interactions API.
Supports audio from URLs, local files, and raw bytes.
"""

from agno.agent import Agent
from agno.media import Audio
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
    # --- Audio from URL ---
    agent.print_response(
        "Describe what you hear in this audio clip.",
        audio=[
            Audio(
                url="https://download.samplelib.com/mp3/sample-3s.mp3",
                mime_type="audio/mp3",
            )
        ],
    )
