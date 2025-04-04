from agno.agent import Agent
from agno.knowledge.firecrawl import FireCrawlKnowledgeBase
from agno.vectordb.qdrant import Qdrant

COLLECTION_NAME = "website-content"

vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")

# Create a knowledge base with the seed URLs
knowledge_base = FireCrawlKnowledgeBase(
    urls=["https://docs.agno.com/introduction"],
    vector_db=vector_db,
)

# Create an agent with the knowledge base
agent = Agent(knowledge=knowledge_base, search_knowledge=True, debug_mode=True)

if __name__ == "__main__":
    # Comment out after first run
    knowledge_base.load(recreate=False)

    agent.print_response("How does agno work?", markdown=True)
