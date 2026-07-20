"""
AgentOS File Input and Output with S3 Storage
=============================================

Serve an AgentOS agent that persists both uploaded input files and generated
output files in S3-compatible object storage. The database stores lightweight
MediaReference records instead of the file bytes.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/file_generation/s3_file_storage.py

Then connect AgentOS and try both paths:

Input file:
    Attach a TXT or CSV file and ask, "Summarize the attached file."

Output file:
    Ask, "Generate a CSV with five fictional employees and their departments."

Requirements:
    pip install 'agno[media-storage-s3]'

Environment:
    AGNO_FILE_OUTPUT_S3_BUCKET must be set to the destination bucket.
    AGNO_FILE_OUTPUT_S3_PREFIX optionally sets the object-key prefix.
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION configure AWS.
    AWS_ENDPOINT_URL can target an S3-compatible service such as MinIO.
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media_storage.s3 import S3MediaStorage
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.file_generation import FileGenerationTools
from dotenv import load_dotenv

load_dotenv()

bucket = os.getenv("AGNO_FILE_OUTPUT_S3_BUCKET")
if not bucket:
    raise ValueError(
        "AGNO_FILE_OUTPUT_S3_BUCKET must be set to the destination S3 bucket"
    )

db = SqliteDb(db_file="tmp/agentos_s3_file_storage.db")
storage = S3MediaStorage(
    bucket=bucket,
    region=os.getenv("AWS_REGION", "us-east-1"),
    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    prefix=os.getenv("AGNO_FILE_OUTPUT_S3_PREFIX", "agno/agentos/files/"),
    presigned_url_expiry=3600,
)

file_agent = Agent(
    id="s3-file-agent",
    name="S3 File Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    media_storage=storage,
    store_media=True,
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

agent_os = AgentOS(
    id="agentos-s3-file-storage",
    name="AgentOS S3 File Storage",
    agents=[file_agent],
    db=db,
    media_storage=storage,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="s3_file_storage:app", reload=True)
