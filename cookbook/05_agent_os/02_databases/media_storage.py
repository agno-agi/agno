"""
External Media Storage
======================

Demonstrates keeping file bytes out of the database. AgentOS sends both attached and
generated files to object storage and persists only a MediaReference.

Set AGNO_FILE_OUTPUT_S3_BUCKET to the destination bucket.

Prerequisites: OPENAI_API_KEY, AWS credentials, and pip install 'agno[s3]'
Run: .venvs/demo/bin/python cookbook/05_agent_os/02_databases/media_storage.py
Try: Attach a CSV and ask "Summarize the attached file", then ask for a generated CSV
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media.storage.s3 import AsyncS3MediaStorage
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.file_generation import FileGenerationTools
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

db = SqliteDb(db_file="tmp/agentos_media_storage.db")
storage = AsyncS3MediaStorage(
    bucket=bucket,
    region=os.getenv(
        "AWS_REGION"
    ),  # unset falls through to boto3 (AWS_DEFAULT_REGION, ~/.aws/config)
    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    prefix=os.getenv("AGNO_FILE_OUTPUT_S3_PREFIX", "agno/agentos/files/"),
    presigned_url_expiry=3600,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

file_agent = Agent(
    id="media-storage-agent",
    name="Media Storage Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    media_storage=storage,
    store_media=True,
    add_history_to_context=True,  # so a follow-up turn can refer back to the attached file
    tools=[FileGenerationTools(all=True)],
    description="Analyze uploaded files and generate files stored in S3.",
    instructions=[
        "Read and answer questions about attached input files.",
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
    id="agentos-media-storage",
    name="AgentOS Media Storage",
    agents=[file_agent],
    db=db,
    media_storage=storage,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="media_storage:app", reload=True)
