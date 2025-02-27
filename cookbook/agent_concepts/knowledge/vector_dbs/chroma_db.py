# install chromadb - `pip install chromadb`

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.chroma import ChromaDb

# Initialize ChromaDB
vector_db = ChromaDb(collection="recipes", path="tmp/chromadb", persistent_client=True)

# Create knowledge base
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

knowledge_base.load(recreate=False)  # Comment out after first run

# Create and use the agent
agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
agent.print_response("Show me how to make Tom Kha Gai", markdown=True)
