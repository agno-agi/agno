"""
Example: Using LocalMediaStorage for development and testing.

LocalMediaStorage saves media files to the local filesystem instead of S3. In production use S3MediaStorage or another cloud storage option.

Important: By default, only media with content bytes or a local filepath is stored;
URL media is skipped. This is the default behaviour as downloading every URL could
grow the storage too much, and some of these URLs are probably public -- creating a
copy of every media may not be ideal.

To change this behavior and download every media from all sources (filepath, content
bytes, and url), instantiate the MediaStorage with persist_remote_urls=True.
Then, whatever media you send to the agent, it will be downloaded and stored locally,
and only a reference will be stored in the DB.
"""

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media_storage.local import LocalMediaStorage
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

storage = LocalMediaStorage(
    base_path="./tmp/media_storage",
    # Optional: set base_url if serving files via a local HTTP server
    # base_url="http://localhost:8080/media",
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    media_storage=storage,
    db=SqliteDb(db_file="tmp/data.db"),
    # db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")  # Postgres option
)

# Download image content first so media storage can offload it
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

# URL-only media is NOT stored locally by default -- it is skipped during offload.
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
# This will download every URL-only media automatically and store it locally.
# ---------------------------------------------------------------------------

storage_with_persist = LocalMediaStorage(
    base_path="./tmp/media_storage",
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

# After running, check ./tmp/media_storage/ for the saved media files
# and .meta.json sidecar files with metadata.
