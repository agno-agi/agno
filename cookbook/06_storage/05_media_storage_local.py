"""
Local Media Storage
===================

LocalMediaStorage saves media files to the local filesystem instead of S3, useful for
development and testing. In production use S3MediaStorage or another cloud backend.

When media_storage is configured, media content (images, audio, video, files) is written
to storage and only a lightweight MediaReference is kept in the database.

By default only media with content bytes or a local filepath is offloaded; URL-only media
is skipped (downloading every URL could grow storage unexpectedly, and many URLs are already
public). To download and store media from every source -- filepath, content bytes, and url --
set persist_remote_urls=True on the storage.
"""

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media_storage.local import LocalMediaStorage
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

# Create the storage. If you want to use async use AsyncLocalMediaStorage instead.
storage = LocalMediaStorage(
    base_path="./tmp/media_storage",
    # Optional: set base_url if serving files via a local HTTP server
    # base_url="http://localhost:8080/media",
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    media_storage=storage,
    db=SqliteDb(db_file="tmp/data.db"),
    # db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")  # Postgres option
)

# Download image content first so media storage can offload it
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

# URL-only media is NOT stored locally by default -- it is skipped during offload.
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
# This will download every URL-only media automatically and store it locally.
# ---------------------------------------------------------------------------

# Create the storage. If you want to use async use AsyncLocalMediaStorage instead.
storage_with_persist = LocalMediaStorage(
    base_path="./tmp/media_storage",
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

# After running, check ./tmp/media_storage/ for the saved media files
# (a .meta.json sidecar is written alongside each file when filename/mime-type/metadata is available).
