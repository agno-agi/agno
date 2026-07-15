"""
GCS Media Storage
=================

GCSMediaStorage offloads media content (images, audio, video, files) to Google Cloud Storage.
The content is uploaded to GCS and only a lightweight MediaReference is stored in the database.

By default only media with content bytes or a local filepath is offloaded; URL-only media
is skipped (downloading every URL could grow storage unexpectedly, and many URLs are already
public). To download and store media from every source -- filepath, content bytes, and url --
set persist_remote_urls=True on the storage.

Requirements:
    pip install 'agno[media-storage-gcs]'

Environment:
    Authenticate with application-default credentials (`gcloud auth application-default login`)
    or a service-account JSON via credentials_path. MEDIA_GCS_BUCKET to pick the bucket;
    GCP_PROJECT to set the project.
"""

import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media_storage.gcs import GCSMediaStorage
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

# Create the storage. If you want to use async use AsyncGCSMediaStorage instead.
storage = GCSMediaStorage(
    bucket=os.getenv(
        "MEDIA_GCS_BUCKET", "my-agno-media"
    ),  # set MEDIA_GCS_BUCKET to a bucket you own
    project=os.getenv("GCP_PROJECT"),  # optional if a default project is configured
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    media_storage=storage,
    db=SqliteDb(db_file="tmp/data.db"),
    # db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")  # Postgres option
)

# Download image content first so media storage can offload it to GCS
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

# URL-only media is NOT stored in GCS by default -- it is skipped during offload.
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
# This will download every URL-only media automatically and store it in GCS.
# ---------------------------------------------------------------------------

storage_with_persist = GCSMediaStorage(
    bucket=os.getenv(
        "MEDIA_GCS_BUCKET", "my-agno-media"
    ),  # set MEDIA_GCS_BUCKET to a bucket you own
    project=os.getenv("GCP_PROJECT"),  # optional if a default project is configured
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
