"""This cookbook shows how to add content from a local file to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/01_from_path.py` to run the cookbook
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.cloud_storage.cloud_storage import S3Config, GCSConfig

contents_db=PostgresDb(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        knowledge_table="knowledge_contents",
    )

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    contents_db=contents_db,
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

config = S3Config(
    bucket_name="agno-public",
    key="recipes/ThaiRecipes.pdf"
)

# Add from S3 bucket
knowledge.add_content(
    name="S3 PDF",
    config=config,
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=True
)

config.key = "prompts/system_promt.txt"
# Add from S3 bucket
knowledge.add_content(
    name="S3 Text",
    config=config,
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=True
)

config.key = "demo_data/agents.md"
# Add from S3 bucket
knowledge.add_content(
    name="S3 Markdown",
    config=config,
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=False
)

# # Add from GCS
# knowledge.add_content(
#     name="GCS PDF",
#     config=GCSConfig(bucket_name="agno-public", key="recipes/ThaiRecipes.pdf"),
#     metadata={"user_tag": "Engineering Candidates"},
# )

# knowledge.add_content(
#     name="URL",
#     url="https://docs.agno.com/introduction",
#     metadata={"user_tag": "Engineering Candidates"},
#     skip_if_exists=True,
#     upsert=False,
# )

# agent = Agent(
#     name="My Agent",
#     description="Agno 2.0 Agent Implementation",
#     knowledge=knowledge,
#     search_knowledge=True,
#     debug_mode=True,
# )

# agent.print_response(
#     "Who is the best candidate for the role of a software engineer?",
#     markdown=True,
# )
