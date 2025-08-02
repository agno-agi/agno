"""
This agent answers questions using knowledge from a PDF stored in a Google Cloud Storage (GCS) bucket.

Setup Steps:
1. Install required libraries: agno, google-cloud-storage, psycopg-binary (for PostgreSQL vector DB).
2. Set up your GCS bucket and upload your PDF file.
3. For public GCS buckets: No authentication needed, just set the bucket and PDF path.
4. For private GCS buckets:
   - Grant the service account Storage Object Viewer access to the bucket via Google Cloud Console
   - Export GOOGLE_APPLICATION_CREDENTIALS with the path to your service account JSON before running the script
5. Update 'bucket_name' and 'blob_name' in the script to your PDF's location.
6. Run the script to load the knowledge base and ask questions.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.gcs.pdf import GCSPDFKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = GCSPDFKnowledgeBase(
    bucket_name="your-gcs-bucket",
    blob_name="path/to/your.pdf",
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)
agent = Agent(knowledge=knowledge_base, search_knowledge=True)

if __name__ == "__main__":
    asyncio.run(knowledge_base.aload(recreate=False))  # Comment out after first run

    asyncio.run(agent.aprint_response("How to make Thai curry?", markdown=True))
