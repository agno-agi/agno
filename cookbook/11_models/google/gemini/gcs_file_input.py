"""
Example: Analyze files directly from Google Cloud Storage (GCS).

The Gemini API now supports GCS URIs natively (up to 2GB).
No need to download or re-upload - just pass the gs:// URI directly.

Requirements:
- Vertex AI must be enabled (GCS URIs require OAuth, not API keys)
- Run: gcloud auth application-default login
- Set environment variables: GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION
- Your GCS bucket must be accessible to your credentials

Supported formats: PDF, JSON, HTML, CSS, XML, images (PNG, JPEG, WebP, GIF)
"""

import os

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

# GCS requires Vertex AI (OAuth credentials), not API keys
agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash",
        vertexai=True,
        project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
    ),
    markdown=True,
)

# Pass GCS URI directly - no download or re-upload needed
agent.print_response(
    "Summarize this document and extract key insights.",
    files=[
        File(
            url="gs://cloud-samples-data/generative-ai/pdf/2312.11805v3.pdf",  # Sample PDF
            mime_type="application/pdf",
        )
    ],
)
