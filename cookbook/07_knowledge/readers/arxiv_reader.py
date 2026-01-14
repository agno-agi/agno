from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.arxiv_reader import ArxivReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with the ArXiv documents
knowledge = Knowledge(
    # Table name: ai.arxiv_documents
    vector_db=PgVector(
        table_name="arxiv_documents",
        db_url=db_url,
    ),
)
# Load the knowledge
knowledge.add_content(
    topics=["Generative AI", "Machine Learning"],
    reader=ArxivReader(),
)

# Create an agent with the knowledge
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

# Ask the agent about the knowledge
agent.print_response("What can you tell me about Generative AI?", markdown=True)
