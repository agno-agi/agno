"""
Reading and Deleting Session Media
==================================

Demonstrates the AgentOS media routes: attach a file to a run, read it back through the
session, then delete the session and its stored objects together.

Media outlives a session by default. The reference on the run is the only record of which
object belongs to which session, so delete_media=true reads the keys off the rows before
they go, then sweeps the objects.

Set AGNO_FILE_OUTPUT_S3_BUCKET to the destination bucket.

Prerequisites: OPENAI_API_KEY, AWS credentials, and pip install 'agno[s3]'
Run: .venvs/demo/bin/python cookbook/05_agent_os/02_databases/media_storage_delete.py
Try: Attach a file to a run, then GET /sessions/{session_id} to see the MediaReference,
     GET /sessions/{session_id}/media/{storage_key} to stream it back, and
     DELETE /sessions/{session_id}?delete_media=true to remove the rows and the objects
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media.storage.s3 import AsyncS3MediaStorage
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Create Database and Media Storage
# ---------------------------------------------------------------------------

bucket = os.getenv("AGNO_FILE_OUTPUT_S3_BUCKET")
if not bucket:
    raise ValueError(
        "AGNO_FILE_OUTPUT_S3_BUCKET must be set to the destination S3 bucket"
    )

db = SqliteDb(db_file="tmp/agentos_media_delete.db")
storage = AsyncS3MediaStorage(
    bucket=bucket,
    region=os.getenv(
        "AWS_REGION"
    ),  # unset falls back to AWS_DEFAULT_REGION or ~/.aws/config
    prefix="agno/agentos/files/",
    presigned_url_expiry=3600,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

file_agent = Agent(
    id="media-delete-agent",
    name="Media Delete Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    media_storage=storage,
    store_media=True,
    description="Answer questions about attached files.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="agentos-media-delete",
    name="AgentOS Media Delete",
    agents=[file_agent],
    db=db,
    media_storage=storage,  # the read and delete routes resolve keys through this
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="media_storage_delete:app", reload=True)
