"""
Google Cloud Storage Media Storage
==================================

Demonstrates keeping media bytes out of the database. AgentOS sends attached and
generated files to Google Cloud Storage and persists only a MediaReference.

Set AGNO_FILE_OUTPUT_GCS_BUCKET to the destination bucket. Authenticate with
Application Default Credentials or set GOOGLE_APPLICATION_CREDENTIALS to a
service-account JSON file.

Prerequisites: OPENAI_API_KEY, Google Cloud credentials, and pip install 'agno[gcs]'
Run: .venvs/demo/bin/python cookbook/05_agent_os/02_databases/gcs_media_storage.py
Try: Attach an image or CSV and ask about it, then ask the agent to generate a CSV
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media.storage.gcs import AsyncGCSMediaStorage
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.file_generation import FileGenerationTools
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Create Database and Media Storage
# ---------------------------------------------------------------------------

bucket = os.getenv("AGNO_FILE_OUTPUT_GCS_BUCKET")
if not bucket:
    raise ValueError(
        "AGNO_FILE_OUTPUT_GCS_BUCKET must be set to the destination GCS bucket"
    )

db = SqliteDb(db_file="tmp/agentos_gcs_media_storage.db")
storage = AsyncGCSMediaStorage(
    bucket=bucket,
    project=os.getenv("GCP_PROJECT"),
    credentials_path=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
    prefix="agno/agentos/files/",
    presigned_url_expiry=3600,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

file_agent = Agent(
    id="gcs-media-storage-agent",
    name="GCS Media Storage Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    media_storage=storage,
    store_media=True,
    add_history_to_context=True,
    tools=[FileGenerationTools(all=True)],
    description="Analyze uploaded media and generate files stored in GCS.",
    instructions=[
        "Read and answer questions about attached media and files.",
        "Use the appropriate file-generation tool when the user requests an output file.",
        "Always use a descriptive filename with the correct extension.",
        "Briefly explain what you read or generated.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="agentos-gcs-media-storage",
    name="AgentOS GCS Media Storage",
    agents=[file_agent],
    db=db,
    media_storage=storage,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="gcs_media_storage:app", reload=True)
