"""
- This agent answers questions using knowledge from a PDF stored in a Google Cloud Storage (GCS) bucket.
- Required libraries: agno, google-cloud-storage, psycopg2-binary (for PostgreSQL vector DB).
- For public GCS buckets: No authentication needed, just set the bucket and PDF path.
- For private GCS buckets: Grant the service account Storage Object Viewer access to the bucket via Google Cloud Console, and export GOOGLE_APPLICATION_CREDENTIALS with the path to your service account JSON before running the script.
- Update 'bucket_name' and 'blob_name' in the script to your PDF's location.
"""

from agno.agent import Agent
from agno.knowledge.gcs.pdf import GCSPDFKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = GCSPDFKnowledgeBase(
    bucket_name="your-gcs-bucket",
    blob_name="path/to/your.pdf",
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)
knowledge_base.load(recreate=False)  # Comment out after first run

agent = Agent(knowledge=knowledge_base, search_knowledge=True)
agent.print_response("How to make Thai curry?", markdown=True)
