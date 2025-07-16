from agno.agent import Agent
from agno.knowledge.wikipedia import WikipediaKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with the PDFs from the data/pdfs directory
knowledge_base = WikipediaKnowledgeBase(
    topics=["Manchester United", "Real Madrid"],
    # Table name: ai.wikipedia_documents
    vector_db=PgVector(
        table_name="wikipedia_documents",
        db_url=db_url,
    ),
)
# Load the knowledge base
knowledge_base.load(recreate=False)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

# Ask the agent about the knowledge base
agent.print_response(
    "Which team is objectively better, Manchester United or Real Madrid?"
)
