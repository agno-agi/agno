from pathlib import Path

from agno.agent import Agent
from agno.knowledge.text import TextKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


# Initialize the TextKnowledgeBase
knowledge_base = TextKnowledgeBase(
    path=Path("data/docs"),  # Table name: ai.text_documents
    vector_db=PgVector(
        table_name="text_documents",
        db_url=db_url,
    ),
    num_documents=5,  # Number of documents to return on search
)
# Load the knowledge base
knowledge_base.load(recreate=False)

# Initialize the Assistant with the knowledge_base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

# Use the agent
agent.print_response("Ask me about something from the knowledge base", markdown=True)
