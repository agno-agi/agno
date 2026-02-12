"""
Example: Using S3MediaStorage to offload media to external object storage.

When media_storage is configured, media content (images, audio, video, files)
is uploaded to S3 before being stored in the database. Only lightweight
MediaReference objects (with pre-signed URLs) are stored in the DB.

Important: By default, only media with content bytes or a local filepath is offloaded;
URL media is skipped. This is the default behaviour as downloading every URL could
grow the storage too much, and some of these URLs are probably public -- creating a
copy of every media may not be ideal.

To change this behavior and download every media from all sources (filepath, content
bytes, and url), instantiate the MediaStorage with persist_remote_urls=True.
Then, whatever media you send to the agent, it will be downloaded and stored in S3,
and only a reference with pre-signed URL will be stored in the DB.

Requirements:
    pip install 'agno[media-storage-s3]'

Environment:
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION (or configure via boto3)
"""

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media_storage.s3 import S3MediaStorage
from agno.models.openai import OpenAIChat
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

storage = S3MediaStorage(
    bucket="my-agno-media",
    region="us-east-1",
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    media_storage=storage,
    db=SqliteDb(db_file="tmp/data.db"),
    # db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")  # Postgres option
)

# Download image content first so media storage can offload it to S3
image_url = (
    "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
)
image_bytes = httpx.get(image_url).content

agent.print_response(
    "What do you see in this image?",
    images=[
        Image(
            content=image_bytes,
            mime_type="image/jpeg",
        )
    ],
)

# URL-only media is NOT stored in S3 by default -- it is skipped during offload.
agent.print_response(
    "What do you see in this image?",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
)

# ---------------------------------------------------------------------------
# Approach 2: Use the flag persist_remote_urls=True.
# This will download every URL-only media automatically and store it in S3.
# ---------------------------------------------------------------------------

storage_with_persist = S3MediaStorage(
    bucket="my-agno-media",
    region="us-east-1",
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
    persist_remote_urls=True,
)

agent_with_persist = Agent(
    model=OpenAIChat(id="gpt-4o"),
    media_storage=storage_with_persist,
    db=SqliteDb(db_file="tmp/data.db"),
    # db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")  # Postgres option
)

# URL-only images are automatically downloaded and stored when persist_remote_urls=True
agent_with_persist.print_response(
    "What do you see in this image?",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
)
