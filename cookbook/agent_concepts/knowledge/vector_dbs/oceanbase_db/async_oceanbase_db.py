import asyncio

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.openai import OpenAILike
from agno.vectordb.oceanbase.oceanbase import OceanBase

vector_db = OceanBase(
    collection="recipes",
    uri="127.0.0.1:2881",
    user="root@test",
    password="test",
    db_name="test",
    embedder=OpenAIEmbedder(),
)

# Create knowledge base
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

# Create and use the agent
agent = Agent(
    knowledge=knowledge_base,
    model=OpenAILike(),
    show_tool_calls=True,
    markdown=True,
    # debug_mode=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge_base.aload(recreate=False))

    # Create and use the agent
    asyncio.run(agent.aprint_response("How to make Tom Kha Gai", markdown=True))
