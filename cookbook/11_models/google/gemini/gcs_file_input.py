"""
Example: Analyze files directly from Google Cloud Storage (GCS).

The Gemini API now supports GCS URIs natively (up to 2GB).
No need to download or re-upload - just pass the gs:// URI directly.

Requirements:
- Your GCS bucket must be accessible to the Gemini API service account
- Or use OAuth credentials with read access to the bucket

Supported formats: PDF, JSON, HTML, CSS, XML, images (PNG, JPEG, WebP, GIF)
"""

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    markdown=True,
)

# Pass GCS URI directly - no download or re-upload needed
agent.print_response(
    "Summarize this document and extract key insights.",
    files=[
        File(
            url="gs://your-bucket/path/to/document.pdf",
            mime_type="application/pdf",
        )
    ],
)
