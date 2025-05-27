from agno.agent import Agent
from agno.knowledge.website import WebsiteKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.vectordb.pineconedb import PineconeDb

# Initialize Pinecone
vector_db = PineconeDb(
    dimension=1536,
    name="agnodocs",
    spec=dict(serverless=dict(cloud="aws", region="us-east-1")),
)

# Step 1: Initialize knowledge base with documents and metadata
knowledge_base = WebsiteKnowledgeBase(
    num_documents=3,
    urls=["https://docs.agno.com/introduction"],
    max_depth=5,
    max_links=10,
    vector_db=vector_db,
)

# Load all documents into the vector database
# knowledge_base.load(recreate=True)

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4.1-nano", temperature=0),
    knowledge=knowledge_base,
    search_knowledge=True,
)

agent.print_response(
    "What integrations are shown?",
    knowledge_filters={"url": "https://docs.agno.com/examples/introduction"},
    markdown=True,
)
