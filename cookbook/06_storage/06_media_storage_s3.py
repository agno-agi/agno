"""
S3 Media Storage
================

Demonstrates S3MediaStorage, which offloads media to S3-compatible object storage and keeps
only a MediaReference in the database — never the bytes, and never a pre-signed URL, which
would expire. URL-only media is skipped unless persist_remote_urls=True.

Requirements:
- uv pip install 'agno[s3]'
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
- Set MEDIA_S3_BUCKET to a bucket you own
"""

import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media.storage import S3MediaStorage
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
IMAGE_URL = "https://thumbs.dreamstime.com/b/mountain-landscape-pieniny-national-park-foot-tatra-mountains-mountain-landscape-pieniny-national-park-437239881.jpg?w=768"

# A bucket you do not own makes every upload fail, and offload falls back to inline
# base64 — the run still succeeds, so the failure is easy to miss. Ask for the bucket
# up front instead.
bucket = os.getenv("MEDIA_S3_BUCKET")
if not bucket:
    raise ValueError("MEDIA_S3_BUCKET must be set to an S3 bucket you own")

# ---------------------------------------------------------------------------
# Approach 1: Pre-download the media yourself and send bytes.
# URL-only media is skipped by default.
# ---------------------------------------------------------------------------

storage = S3MediaStorage(
    bucket=bucket,
    region=os.getenv(
        "AWS_REGION"
    ),  # unset falls back to AWS_DEFAULT_REGION or ~/.aws/config
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    media_storage=storage,
    db=SqliteDb(db_file="tmp/data.db"),
)

# ---------------------------------------------------------------------------
# Approach 2: Use the flag persist_remote_urls=True.
# This will download every URL-only media automatically and store it in S3.
# ---------------------------------------------------------------------------

storage_with_persist = S3MediaStorage(
    bucket=bucket,
    region=os.getenv(
        "AWS_REGION"
    ),  # unset falls back to AWS_DEFAULT_REGION or ~/.aws/config
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
    persist_remote_urls=True,
)

agent_with_persist = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    media_storage=storage_with_persist,
    db=SqliteDb(db_file="tmp/data.db"),
)

# ---------------------------------------------------------------------------
# Run the Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Download image content first so media storage can offload it to S3.
    # mime_type gives the stored object its file extension and Content-Type.
    image_bytes = httpx.get(IMAGE_URL, follow_redirects=True).content

    agent.print_response(
        "What do you see in this image?",
        images=[Image(content=image_bytes, format="jpeg", mime_type="image/jpeg")],
    )

    # URL-only media is NOT stored in S3 by default — it is skipped during offload.
    agent.print_response(
        "What do you see in this image?",
        images=[Image(url=IMAGE_URL)],
    )

    # URL-only images are automatically downloaded and stored when persist_remote_urls=True
    agent_with_persist.print_response(
        "What do you see in this image?",
        images=[Image(url=IMAGE_URL)],
    )
