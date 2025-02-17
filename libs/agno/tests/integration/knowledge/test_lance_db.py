# install chromadb - `pip install chromadb`

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.lancedb.lance_db import LanceDb


def test_pdf_url_knowledge_base():
    vector_db = LanceDb(
        table_name="recipes",
        uri="tmp/lancedb",
    )

    # Create knowledge base
    knowledge_base = PDFUrlKnowledgeBase(
        urls=[
            "https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
            "https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        ],
        vector_db=vector_db,
    )

    knowledge_base.load(recreate=True)

    assert vector_db.exists()

    assert vector_db.get_count() == 13  # 3 from the first pdf and 10 from the second pdf

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = agent.run("Show me how to make Tom Kha Gai", markdown=True)

    assert "Tom Kha Gai" in response.content
