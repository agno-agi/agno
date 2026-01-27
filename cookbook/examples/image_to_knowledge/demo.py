"""
Content Sources for Knowledge — DX Design
============================================================

This cookbook demonstrates the API for adding content from various
remote sources (S3, GCS, SharePoint, GitHub, etc.) to Knowledge.

Key Concepts:
- RemoteContentConfig: Base class for configuring remote content sources
- Each source type has its own config: S3Config, GcsConfig, SharePointConfig, GitHubConfig
- Configs are registered on Knowledge via `content_sources` parameter
- Configs have factory methods (.file(), .folder()) to create content references
- Content references are passed to knowledge.insert()
"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import (
    SharePointConfig,
)
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

from cookbook.examples.image_to_knowledge.image_reader import ImageReader

# Database connections
contents_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
vector_db = PgVector(
    table_name="knowledge_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Define content source configs (credentials can come from env vars)

sharepoint = SharePointConfig(
    id="sharepoint",
    name="Product Data",
    tenant_id=getenv("SHAREPOINT_TENANT_ID"),  # or os.getenv("SHAREPOINT_TENANT_ID")
    client_id=getenv("SHAREPOINT_CLIENT_ID"),
    client_secret=getenv("SHAREPOINT_CLIENT_SECRET"),
    hostname=getenv("SHAREPOINT_HOSTNAME"),
    site_id=getenv("SHAREPOINT_SITE_ID"),
)

image_reader = ImageReader(
    name="Agent Based Image Reader",
    description="Reads images and extracts text using an agent",
)

# Create Knowledge with content sources
knowledge = Knowledge(
    name="Company Knowledge Base",
    description="Unified knowledge from multiple sources",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[sharepoint],
    readers={"image_reader": image_reader},
)


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge,
    search_knowledge=True,
)

agent_os = AgentOS(
    knowledge=[knowledge],
    agents=[agent],
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="demo:app", reload=True)

# ============================================================================
# API Usage
# ============================================================================
"""
Once the server is running, you can interact with the Knowledge API.

1. GET /knowledge/config
   Returns available readers, chunkers, and content sources.
   Your custom reader appears under the "readers" key:

   {
     "readers": {
       "image_reader": {
         "id": "image_reader",
         "name": "Agent Based Image Reader",
         "description": "Reads images and extracts text using an agent",
         "chunkers": [
           "FixedSizeChunker",
           "DocumentChunker",
           "RecursiveChunker",
           "SemanticChunker",
           "AgenticChunker"
         ]
       },
       ...
     },
     "chunkers": {
       "FixedSizeChunker": { ... },
       "DocumentChunker": { ... },
       ...
     },
     "remote_content_sources": [
       { "id": "sharepoint", "name": "Product Data", "type": "sharepoint" }
     ]
   }

2. POST /knowledge/remote-content
   Upload content from a remote source using your custom reader.

   curl -X POST 'http://localhost:7777/knowledge/remote-content' \\
     -H 'Content-Type: application/x-www-form-urlencoded' \\
     -d 'config_id=sharepoint' \\
     -d 'path=documents/invoice.png' \\
     -d 'reader_id=image_reader' \\
     -d 'chunker=FixedSizeChunker' \\
     -d 'chunk_size=1000'

   Parameters:
   - config_id: ID of the remote content source (from /knowledge/config)
   - path: Path to the file in the remote source
   - reader_id: ID of the reader to use (e.g., "image_reader")
   - chunker: (optional) Chunking strategy from the reader's supported chunkers
   - chunk_size: (optional) Size of each chunk in characters
   - chunk_overlap: (optional) Overlap between chunks
"""
