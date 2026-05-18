"""
Gemini Interactions - Document Processing
==========================================

Example showing document (PDF) processing with the Interactions API.
Supports documents from URLs, local files, and raw bytes.
"""

from agno.agent import Agent
from agno.media import File
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
    # --- Document from URL ---
    agent.print_response(
        "Summarize this document.",
        files=[
            File(
                url="https://arxiv.org/pdf/1706.03762",
                mime_type="application/pdf",
            )
        ],
    )
