"""
Multi-turn Media Storage
========================

A multi-turn conversation keeps working when store_media=False and a media_storage backend
is configured. On turn 1 the image is offloaded to storage and only a MediaReference is kept
in the database. On turn 2 the agent answers about the image without it being re-sent: the
reference is reloaded from history and its URL refreshed so the model can see the image again,
while the raw bytes never bloat the database.
"""

import shutil
from pathlib import Path

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media_storage.local import LocalMediaStorage
from agno.models.openai import OpenAIResponses
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Setup: store_media=False + LocalMediaStorage (start from a clean slate)
# ---------------------------------------------------------------------------
MEDIA_DIR = "./tmp/multiturn_media"
DB_FILE = "tmp/multiturn.db"

shutil.rmtree(MEDIA_DIR, ignore_errors=True)
Path(DB_FILE).unlink(missing_ok=True)

storage = LocalMediaStorage(base_path=MEDIA_DIR)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    media_storage=storage,
    store_media=False,  # Keep raw bytes out of the DB; only the reference is persisted
    db=SqliteDb(db_file=DB_FILE),
    session_id="multiturn-session",
    add_history_to_context=True,
)

# Download an image to send on the first turn
image_url = "https://picsum.photos/id/15/800/600.jpg"
image_bytes = httpx.get(image_url, follow_redirects=True).content

# ---------------------------------------------------------------------------
# Turn 1: send the image and ask about it
# ---------------------------------------------------------------------------
agent.print_response(
    "What do you see in this image?",
    images=[Image(content=image_bytes, format="jpeg")],
)

# ---------------------------------------------------------------------------
# Turn 2: ask again without re-attaching the image -- it is reloaded from storage
# ---------------------------------------------------------------------------
agent.print_response("What was the image about?")
