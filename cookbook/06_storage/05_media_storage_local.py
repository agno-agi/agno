"""
Local Media Storage
===================

Demonstrates LocalMediaStorage, which writes media to the filesystem and keeps only a
MediaReference in the database. For development; use S3MediaStorage or GCSMediaStorage
in production.

URL-only media is skipped by default. Set persist_remote_urls=True to download and store it.
"""

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media.storage import LocalMediaStorage
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
IMAGE_URL = "https://thumbs.dreamstime.com/b/mountain-landscape-pieniny-national-park-foot-tatra-mountains-mountain-landscape-pieniny-national-park-437239881.jpg?w=768"

# ---------------------------------------------------------------------------
# Approach 1: Pre-download the media yourself and send bytes.
# URL-only media is skipped by default.
# ---------------------------------------------------------------------------

storage = LocalMediaStorage(base_path="./tmp/media_storage")

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
# This will download every URL-only media automatically and store it locally.
# ---------------------------------------------------------------------------

storage_with_persist = LocalMediaStorage(
    base_path="./tmp/media_storage",
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
    # Download image content first so media storage can offload it
    image_bytes = httpx.get(IMAGE_URL, follow_redirects=True).content

    agent.print_response(
        "What do you see in this image?",
        images=[Image(content=image_bytes, format="jpeg", mime_type="image/jpeg")],
    )

    # URL-only media is NOT stored locally by default — it is skipped during offload.
    agent.print_response(
        "What do you see in this image?",
        images=[Image(url=IMAGE_URL)],
    )

    # URL-only images are automatically downloaded and stored when persist_remote_urls=True
    agent_with_persist.print_response(
        "What do you see in this image?",
        images=[Image(url=IMAGE_URL)],
    )
