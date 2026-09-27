"""
Multi-turn Media Storage
========================

Demonstrates a multi-turn conversation over offloaded media. Turn 1 uploads the image to S3
and keeps only a MediaReference; turn 2 asks about it without re-attaching it. The stored
reference is re-signed on read, so the model fetches the image from S3 and the bytes never
travel back through the database.

store=False keeps history client-side; OpenAIResponses would otherwise chain turns via
previous_response_id and turn 2 would send no image at all.

Requirements:
- uv pip install 'agno[s3]'
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
- Set MEDIA_S3_BUCKET to the destination bucket
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
DB_FILE = "tmp/multiturn.db"
IMAGE_URL = "https://picsum.photos/id/15/800/600.jpg"

bucket = os.getenv("MEDIA_S3_BUCKET")
if not bucket:
    raise ValueError("MEDIA_S3_BUCKET must be set to the destination S3 bucket")

storage = S3MediaStorage(
    bucket=bucket,
    region=os.getenv("AWS_REGION"),
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.5", store=False
    ),  # keep history client-side, see docstring
    media_storage=storage,
    db=SqliteDb(db_file=DB_FILE),
    session_id="multiturn-session",
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    image_bytes = httpx.get(IMAGE_URL, follow_redirects=True).content

    # Turn 1: send the image and ask about it
    agent.print_response(
        "What do you see in this image?",
        images=[Image(content=image_bytes, format="jpeg", mime_type="image/jpeg")],
    )

    # Turn 2: ask again without re-attaching it — the reference is re-signed for the model
    agent.print_response("What was the image about?")
