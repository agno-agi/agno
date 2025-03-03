from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.csv import CSVKnowledgeBase
from agno.vectordb.lancedb.lance_db import LanceDb


def test_pdf_knowledge_base():
    vector_db = LanceDb(
        table_name="employees",
        uri="tmp/lancedb",
    )

    print(f"check path{str(Path(__file__).parent / 'data')}")
    # Create a knowledge base with the CSVs from the data/csvs directory
    knowledge_base = CSVKnowledgeBase(
        path=str(Path(__file__).parent / "data"),
        vector_db=vector_db,
    )
    knowledge_base.reader.chunk = False

    knowledge_base.load(recreate=True)

    assert vector_db.exists()

    assert vector_db.get_count() == 1

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = agent.run(
        "Tell me about the the summary of the data passed in the knowledge base in the csv", markdown=True
    )

    assert "knowledge base" in response.content

    # Clean up
    vector_db.drop()


@pytest.mark.asyncio
async def test_pdf_knowledge_base_async():
    vector_db = LanceDb(
        table_name="employees_async_c",
        uri="tmp/lancedb",
    )

    # Create knowledge base
    knowledge_base = CSVKnowledgeBase(
        path=str(Path(__file__).parent / "data"),
        vector_db=vector_db,
    )

    await knowledge_base.aload(recreate=True)
    knowledge_base.reader.chunk = False

    assert await vector_db.async_exists()
    # for 101 rows 6 pages
    assert await vector_db.async_get_count() == 6

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = await agent.arun("Which employees have salaries above 50000?", markdown=True)

    assert "employees" in response.content
    assert any(ingredient in response.content.lower() for ingredient in ["50000", "employees", "salary"])

    # Clean up
    await vector_db.async_drop()
