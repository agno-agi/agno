"""
File Output
===========

Demonstrates file output in AgentOS.

Set AGNO_FILE_OUTPUT_S3_BUCKET to also expose an S3-backed file output agent
that uploads generated files to S3 and returns temporary file.url render links.
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.file_generation import FileGenerationTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/agentos.db")
S3_BUCKET = os.getenv("AGNO_FILE_OUTPUT_S3_BUCKET")
S3_PREFIX = os.getenv("AGNO_FILE_OUTPUT_S3_PREFIX", "agentos-file-output/")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

file_agent = Agent(
    name="File Output Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    send_media_to_model=False,
    tools=[FileGenerationTools(output_directory="tmp")],
    instructions="Just return the file url as it is don't do anythings.",
)

s3_file_agent = (
    Agent(
        name="S3 File Output Agent",
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        send_media_to_model=False,
        tools=[
            FileGenerationTools(
                s3_bucket=S3_BUCKET,
                s3_prefix=S3_PREFIX,
                region_name=AWS_REGION,
                s3_presigned_url_expires_in=3600,
                include_content=False,
            )
        ],
        instructions=[
            "Generate the requested file with FileGenerationTools.",
            "The generated file is uploaded to S3.",
            "Return the temporary file.url render link exactly as it is.",
        ],
    )
    if S3_BUCKET
    else None
)

agents = [s3_file_agent, file_agent] if s3_file_agent else [file_agent]

agent_os = AgentOS(
    id="agentos-demo",
    agents=agents,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="file_output:app", reload=True)
