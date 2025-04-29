import pytest

from agno.agent import Agent
from agno.knowledge.csv_url import CSVUrlKnowledgeBase
from agno.vectordb.lancedb.lance_db import LanceDb


def test_csv_url_knowledge_base():
    vector_db = LanceDb(
        table_name="recipes_2s3",
        uri="tmp/lancedb",
    )
    knowledge_base = CSVUrlKnowledgeBase(
        urls=[
            "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
            "https://agno-public.s3.amazonaws.com/csvs/employees.csv",
        ],
        vector_db=vector_db,
    )

    reader = knowledge_base.reader
    reader.chunk = False

    knowledge_base.load(recreate=True)

    assert vector_db.exists()
    doc_count = vector_db.get_count()
    assert doc_count > 2, f"Expected multiple documents but got {doc_count}"

    # The count should also not be unreasonably large
    assert doc_count < 100, f"Got {doc_count} documents, which seems too many"

    # Query the agent
    agent = Agent(
        knowledge=knowledge_base,
        search_knowledge=True,
        instructions=[
            "You are a helpful assistant that can answer questions.",
            "You can use the search_knowledge_base tool to search the knowledge base of CSVs for information.",
        ],
    )
    response = agent.run("Give me top rated movies", markdown=True)

    # Check that we got relevant content
    assert any(term in response.content.lower() for term in ["movie", "rating", "imdb", "title"])

    # Clean up
    vector_db.drop()


@pytest.mark.asyncio
async def test_csv_url_knowledge_base_async():
    vector_db = LanceDb(
        table_name="recipes_async_2s",
        uri="tmp/lancedb",
    )

    knowledge_base = CSVUrlKnowledgeBase(
        urls=[
            "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
            "https://agno-public.s3.amazonaws.com/csvs/employees.csv",
        ],
        vector_db=vector_db,
    )

    # Set chunk explicitly to False before loading
    reader = knowledge_base.reader
    reader.chunk = False
    await knowledge_base.aload(recreate=True)
    assert await vector_db.async_exists()

    doc_count = await vector_db.async_get_count()
    assert doc_count > 2, f"Expected multiple documents but got {doc_count}"

    # The count should also not be unreasonably large
    assert doc_count < 100, f"Got {doc_count} documents, which seems too many"

    # Query the agent
    agent = Agent(
        knowledge=knowledge_base,
        search_knowledge=True,
        instructions=[
            "You are a helpful assistant that can answer questions.",
            "You can use the async_search_knowledge_base tool to search the knowledge base of CSVs for information.",
        ],
    )
    response = await agent.arun("Which employees have salaries above 50000?", markdown=True)

    assert "employees" in response.content.lower()

    await vector_db.async_drop()
