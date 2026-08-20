"""
Multi-turn Media Storage
========================

Demonstrates a multi-turn conversation over offloaded media. Turn 1 uploads the image and
keeps only a MediaReference; turn 2 asks about it without re-sending it, and the bytes are
re-read from storage.

store=False keeps history client-side; OpenAIResponses would otherwise chain turns via
previous_response_id and turn 2 would send no image at all.
"""

import shutil
from pathlib import Path

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media.storage import LocalMediaStorage
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup: media_storage configured
# ---------------------------------------------------------------------------
MEDIA_DIR = "./tmp/multiturn_media"
DB_FILE = "tmp/multiturn.db"
IMAGE_URL = "https://picsum.photos/id/15/800/600.jpg"

storage = LocalMediaStorage(base_path=MEDIA_DIR)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.5", store=False
    ),  # keep history client-side, see docstring
    media_storage=storage,  # Offload media to storage; only the reference is kept in the DB
    db=SqliteDb(db_file=DB_FILE),
    session_id="multiturn-session",
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Start from a clean slate so turn 1 really offloads for the first time
    shutil.rmtree(MEDIA_DIR, ignore_errors=True)
    Path(DB_FILE).unlink(missing_ok=True)

    image_bytes = httpx.get(IMAGE_URL, follow_redirects=True).content

    # Turn 1: send the image and ask about it
    agent.print_response(
        "What do you see in this image?",
        images=[Image(content=image_bytes, format="jpeg", mime_type="image/jpeg")],
    )

    # Turn 2: ask again without re-attaching the image — it is reloaded from storage
    agent.print_response("What was the image about?")
