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