"""
Example: Analyze files from AWS S3 using pre-signed URLs.

The Gemini API now supports external HTTPS URLs (up to 100MB).
Generate a pre-signed URL from S3 and pass it directly to Gemini.

Requirements:
- AWS credentials configured (via environment variables or ~/.aws/credentials)
- boto3 installed: pip install boto3

Supported formats: PDF, JSON, HTML, CSS, XML, images (PNG, JPEG, WebP, GIF)
"""

import boto3
from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

# Generate a pre-signed URL for your S3 object
s3_client = boto3.client("s3")
presigned_url = s3_client.generate_presigned_url(
    "get_object",
    Params={
        "Bucket": "your-bucket-name",
        "Key": "path/to/document.pdf",
    },
    ExpiresIn=3600,  # URL valid for 1 hour
)

agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    markdown=True,
)

# Pass pre-signed URL directly - Gemini fetches the content
agent.print_response(
    "Summarize this document and extract key insights.",
    files=[
        File(
            url=presigned_url,
            mime_type="application/pdf",
        )
    ],
)
