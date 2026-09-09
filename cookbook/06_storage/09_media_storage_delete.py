"""
Deleting Offloaded Media
========================

Demonstrates deleting a session's stored media along with its rows. Offloaded media outlives
the session by default, because the reference in the row is the only record of which object
belongs to which session — delete the rows first and nothing can find the objects again.

Pass delete_media=True and the keys are read before the rows, then the objects are swept.
The same flag exists on Agent, Team and Workflow, sync and async.

Requirements:
- uv pip install 'agno[s3]'
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
- Set MEDIA_S3_BUCKET to the destination bucket
Run: .venvs/demo/bin/python cookbook/06_storage/09_media_storage_delete.py
"""

import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media.storage.s3 import S3MediaStorage
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
DB_FILE = "tmp/media_delete.db"
PREFIX = "agno/media_delete/"
IMAGE_URL = "https://picsum.photos/id/15/800/600.jpg"

bucket = os.getenv("MEDIA_S3_BUCKET")
if not bucket:
    raise ValueError("MEDIA_S3_BUCKET must be set to the destination S3 bucket")

storage = S3MediaStorage(
    bucket=bucket,
    region=os.getenv("AWS_REGION"),
    prefix=PREFIX,
    presigned_url_expiry=3600,  # 1 hour
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    media_storage=storage,
    db=SqliteDb(db_file=DB_FILE),
)


def stored_keys() -> list:
    import boto3

    client = boto3.client("s3", region_name=os.getenv("AWS_REGION"))
    listing = client.list_objects_v2(Bucket=bucket, Prefix=PREFIX)
    return sorted(obj["Key"] for obj in listing.get("Contents", []))


def describe(session_id: str, image_bytes: bytes) -> None:
    agent.run(
        "What do you see in this image?",
        session_id=session_id,
        images=[Image(content=image_bytes, format="jpeg", mime_type="image/jpeg")],
    )


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    image_bytes = httpx.get(IMAGE_URL, follow_redirects=True).content
    describe("keeps-media", image_bytes)
    describe("sweeps-media", image_bytes)
    print("Stored in S3 after two sessions:", len(stored_keys()))

    # Without the flag the rows go and the objects stay
    agent.delete_session(session_id="keeps-media")
    print("After deleting one session without the flag:", len(stored_keys()))

    # With it, the keys are read off the rows first, then the objects are swept
    agent.delete_session(session_id="sweeps-media", delete_media=True)
    print("After deleting the other with delete_media=True:", len(stored_keys()))
    print("Left behind:", stored_keys())
