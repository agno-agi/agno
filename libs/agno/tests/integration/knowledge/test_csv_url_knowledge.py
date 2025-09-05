import uuid

import pytest

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.csv_reader import CSVUrlReader
from agno.vectordb.lancedb import LanceDb


def test_csv_url_knowledge():
    table_name = f"csv_test_{uuid.uuid4().hex}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    knowledge = Knowledge(
        vector_db=vector_db,
    )

    knowledge.add_content(
        url="https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
        reader=CSVUrlReader(
            chunk=False,
        ),
    )
    knowledge.add_content(
        url="https://agno-public.s3.amazonaws.com/csvs/employees.csv",
        reader=CSVUrlReader(
            chunk=False,
        ),
    )

    assert vector_db.exists()
    doc_count = vector_db.get_count()
    assert doc_count > 2, f"Expected multiple documents but got {doc_count}"

    # The count should also not be unreasonably large
    assert doc_count < 100, f"Got {doc_count} documents, which seems too many"

    # Query the agent
    agent = Agent(
        knowledge=knowledge,
        search_knowledge=True,
        instructions=[
            "You are a helpful assistant that can answer questions.",
            "You can use the search_knowledge tool to search the knowledge base of CSVs for information.",
        ],
    )
    response = agent.run("Give me top rated movies", markdown=True)

    # Check that we got relevant content
    assert any(term in response.content.lower() for term in ["movie", "rating", "imdb", "title"])

    # Clean up
    vector_db.drop()


@pytest.mark.asyncio
async def test_csv_url_knowledge_async():
    table_name = f"csv_test_{uuid.uuid4().hex}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    knowledge = Knowledge(
        vector_db=vector_db,
    )

    # Set chunk explicitly to False
    await knowledge.add_contents_async(
        urls=[
            "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
            "https://agno-public.s3.amazonaws.com/csvs/employees.csv",
        ],
        reader=CSVUrlReader(
            chunk=False,
        ),
    )
    assert await vector_db.async_exists()

    doc_count = await vector_db.async_get_count()
    assert doc_count > 2, f"Expected multiple documents but got {doc_count}"

    # The count should also not be unreasonably large
    assert doc_count < 100, f"Got {doc_count} documents, which seems too many"

    # Query the agent
    agent = Agent(
        knowledge=knowledge,
        search_knowledge=True,
        instructions=[
            "You are a helpful assistant that can answer questions.",
            "You can use the search_knowledge tool to search the knowledge base of CSVs for information.",
        ],
    )
    response = await agent.arun("Which employees have salaries above 50000?", markdown=True)

    assert "employees" in response.content.lower()

    await vector_db.async_drop()
