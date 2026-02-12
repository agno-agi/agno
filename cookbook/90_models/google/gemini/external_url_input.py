"""
Example: Analyze files from public HTTPS URLs.

The Gemini API now supports external HTTPS URLs (up to 100MB).
Pass public URLs directly without downloading first.

This works with:
- Public URLs (no authentication required)
- Pre-signed URLs from AWS S3
- SAS URLs from Azure Blob Storage
- Any accessible HTTPS URL

Supported formats: PDF, JSON, HTML, CSS, XML, images (PNG, JPEG, WebP, GIF)

Note: External URL support requires Gemini 3.x models (e.g., gemini-3-flash-preview).
      Gemini 2.0 models do not support this feature.
"""

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    markdown=True,
)

# Pass public URL directly - Gemini fetches the content
agent.print_response(
    "Summarize this document.",
    files=[
        File(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            mime_type="application/pdf",
        )
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
