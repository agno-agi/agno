import pytest

from agno.agent import Agent
from agno.knowledge.csv_url import CSVUrlKnowledgeBase
from agno.vectordb.lancedb.lance_db import LanceDb


def test_csv_url_knowledge_base():
    vector_db = LanceDb(
        table_name="recipes_2s3",
        uri="tmp/lancedb",
    )

    # Create knowledge base
    knowledge_base = CSVUrlKnowledgeBase(
        urls=[
            "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
            "https://agno-public.s3.amazonaws.com/csvs/employees.csv",
        ],
        vector_db=vector_db,
    )
    knowledge_base.reader.chunk = False

    knowledge_base.load(recreate=True)

    assert vector_db.exists()

    assert vector_db.get_count() == 2
    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = agent.run("Give me top rated movies", markdown=True)

    assert "knowledge base" in response.content

    # Clean up
    vector_db.drop()


@pytest.mark.asyncio
async def test_csv_url_knowledge_base_async():
    vector_db = LanceDb(
        table_name="recipes_async_2s",
        uri="tmp/lancedb",
    )

    # Create knowledge base
    knowledge_base = CSVUrlKnowledgeBase(
        urls=[
            "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
            "https://agno-public.s3.amazonaws.com/csvs/employees.csv",
        ],
        vector_db=vector_db,
    )
    knowledge_base.reader.chunk = False

    await knowledge_base.aload(recreate=True)

    assert await vector_db.async_exists()
    assert await vector_db.async_get_count() == 57

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = await agent.arun("Which employees have salaries above 50000?", markdown=True)

    assert "employees" in response.content
    assert any(ingredient in response.content.lower() for ingredient in ["50000", "employees", "salary"])

    # Clean up
    await vector_db.async_drop()
