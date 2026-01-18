import asyncio
import os

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.filters import IN
from agno.knowledge.knowledge import Knowledge
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.pgvector import PgVector

# Download all sample CVs and get their paths
downloaded_cv_paths = download_knowledge_filters_sample_data(
    num_files=5, file_extension=SampleDataFileExtension.DOCX
)

# Clean up old databases
if os.path.exists("tmp/knowledge_contents.db"):
    os.remove("tmp/knowledge_contents.db")
db = AsyncSqliteDb(
    db_file="tmp/knowledge_contents.db",
)

# Initialize Vector Database
vector_db = PgVector(
    table_name="CVs",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Step 1: Initialize knowledge base with documents and metadata
# ------------------------------------------------------------------------------
# When initializing the knowledge base, we can attach metadata that will be used for filtering
# This metadata can include user IDs, document types, dates, or any other attributes

knowledge = Knowledge(
    name="Async Filtering",
    vector_db=vector_db,
    contents_db=db,
)

asyncio.run(
    knowledge.add_contents_async(
        [
            {
                "path": downloaded_cv_paths[0],
                "metadata": {
                    "user_id": "jordan_mitchell",
                    "document_type": "cv",
                    "year": 2025,
                },
            },
            {
                "path": downloaded_cv_paths[1],
                "metadata": {
                    "user_id": "taylor_brooks",
                    "document_type": "cv",
                    "year": 2025,
                },
            },
            {
                "path": downloaded_cv_paths[2],
                "metadata": {
                    "user_id": "morgan_lee",
                    "document_type": "cv",
                    "year": 2025,
                },
            },
            {
                "path": downloaded_cv_paths[3],
                "metadata": {
                    "user_id": "casey_jordan",
                    "document_type": "cv",
                    "year": 2025,
                },
            },
            {
                "path": downloaded_cv_paths[4],
                "metadata": {
                    "user_id": "alex_rivera",
                    "document_type": "cv",
                    "year": 2025,
                },
            },
        ],
    )
)


# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------

# Option 1: Filters on the Agent
# Initialize the Agent with the knowledge base and filters
agent = Agent(
    db=db,
    knowledge=knowledge,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Query for Jordan Mitchell's experience and skills
    asyncio.run(
        agent.aprint_response(
            "Search the knowledge base for the candidate's experience and skills",
            knowledge_filters={"user_id": "jordan_mitchell"},
            markdown=True,
        )
    )

    asyncio.run(
        agent.aprint_response(
            "Tell me about the candidate's experience and skills",
            knowledge_filters=[(IN("user_id", ["jordan_mitchell"]))],
            markdown=True,
        )
    )
