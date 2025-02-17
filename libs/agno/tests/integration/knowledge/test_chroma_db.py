# install chromadb - `pip install chromadb`

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.chroma import ChromaDb


def test_pdf_url_knowledge_base():
    # Initialize ChromaDB
    vector_db = ChromaDb(collection="recipes", path="tmp/chromadb", persistent_client=True)

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

    assert vector_db.get_count() == 13  # 10 from the first pdf and 3 from the second pdf

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = agent.run("Show me how to make Tom Kha Gai", markdown=True)

    assert "Tom Kha Gai" in response.content
