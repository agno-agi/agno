from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.website_reader import WebsiteReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with website content
knowledge = Knowledge(
    # Table name: ai.website_documents
    vector_db=PgVector(
        table_name="website_documents",
        db_url=db_url,
        embedder=OpenAIEmbedder(),
    ),
)
# Load the knowledge
knowledge.insert(
    url="https://en.wikipedia.org/wiki/OpenAI",
    reader=WebsiteReader(),
)

# Create an agent with the knowledge
agent = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
)

# Ask the agent about the knowledge
agent.print_response("What can you tell me about Generative AI?", markdown=True)
