"""
S3 Media Storage
================

S3MediaStorage offloads media content (images, audio, video, files) to S3-compatible object
storage. The content is uploaded to S3 and only a lightweight MediaReference (with a
pre-signed URL) is stored in the database.

By default only media with content bytes or a local filepath is offloaded; URL-only media
is skipped (downloading every URL could grow storage unexpectedly, and many URLs are already
public). To download and store media from every source -- filepath, content bytes, and url --
set persist_remote_urls=True on the storage.

Requirements:
    pip install 'agno[media-storage-s3]'

Environment:
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION (or configure via boto3).
    MEDIA_S3_BUCKET to pick the bucket; AWS_ENDPOINT_URL to target an S3-compatible
    service such as MinIO.
"""

import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media_storage.s3 import S3MediaStorage
from agno.models.openai import OpenAIResponses
from dotenv import load_dotenv

# from agno.db.postgres import PostgresDb

# ---------------------------------------------------------------------------
# Setup of .env file
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Approach 1: Pre-download the media yourself and send bytes.
# URL-only media is skipped by default.
# ---------------------------------------------------------------------------

# Create the storage. If you want to use async use AsyncS3MediaStorage instead.
storage = S3MediaStorage(
    bucket=os.getenv(
        "MEDIA_S3_BUCKET", "my-agno-media"
    ),  # set MEDIA_S3_BUCKET to a bucket you own
    region=os.getenv("AWS_REGION", "us-east-1"),
    endpoint_url=os.getenv(
        "AWS_ENDPOINT_URL"
    ),  # set for an S3-compatible service (e.g. MinIO)
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    media_storage=storage,
    db=SqliteDb(db_file="tmp/data.db"),
    # db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")  # Postgres option
)

# Download image content first so media storage can offload it to S3
image_url = "https://thumbs.dreamstime.com/b/mountain-landscape-pieniny-national-park-foot-tatra-mountains-mountain-landscape-pieniny-national-park-437239881.jpg?w=768"
image_bytes = httpx.get(image_url, follow_redirects=True).content

agent.print_response(
    "What do you see in this image?",
    images=[
        Image(
            content=image_bytes,
            format="jpeg",
        )
    ],
)

# URL-only media is NOT stored in S3 by default -- it is skipped during offload.
agent.print_response(
    "What do you see in this image?",
    images=[
        Image(
            url="https://thumbs.dreamstime.com/b/mountain-landscape-pieniny-national-park-foot-tatra-mountains-mountain-landscape-pieniny-national-park-437239881.jpg?w=768"
        )
    ],
)

# ---------------------------------------------------------------------------
# Approach 2: Use the flag persist_remote_urls=True.
# This will download every URL-only media automatically and store it in S3.
# ---------------------------------------------------------------------------

storage_with_persist = S3MediaStorage(
    bucket=os.getenv(
        "MEDIA_S3_BUCKET", "my-agno-media"
    ),  # set MEDIA_S3_BUCKET to a bucket you own
    region=os.getenv("AWS_REGION", "us-east-1"),
    endpoint_url=os.getenv(
        "AWS_ENDPOINT_URL"
    ),  # set for an S3-compatible service (e.g. MinIO)
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
    persist_remote_urls=True,
)

agent_with_persist = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    media_storage=storage_with_persist,
    db=SqliteDb(db_file="tmp/data.db"),
    # db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")  # Postgres option
)

# URL-only images are automatically downloaded and stored when persist_remote_urls=True
agent_with_persist.print_response(
    "What do you see in this image?",
    images=[
        Image(
            url="https://thumbs.dreamstime.com/b/mountain-landscape-pieniny-national-park-foot-tatra-mountains-mountain-landscape-pieniny-national-park-437239881.jpg?w=768"
        )
    ],
)
