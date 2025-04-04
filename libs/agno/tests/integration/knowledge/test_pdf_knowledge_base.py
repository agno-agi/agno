from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.pdf import PDFKnowledgeBase
from agno.vectordb.lancedb.lance_db import LanceDb


def test_pdf_knowledge_base():
    vector_db = LanceDb(
        table_name="recipes",
        uri="tmp/lancedb",
    )

    # Create a knowledge base with the PDFs from the data/pdfs directory
    knowledge_base = PDFKnowledgeBase(
        path=str(Path(__file__).parent / "data"),
        vector_db=vector_db,
    )

    knowledge_base.load(recreate=True)

    assert vector_db.exists()

    assert vector_db.get_count() == 10

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = agent.run("Show me how to make Tom Kha Gai", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] == "search_knowledge_base"

    # Clean up
    vector_db.drop()


@pytest.mark.asyncio
async def test_pdf_knowledge_base_async():
    vector_db = LanceDb(
        table_name="recipes_async",
        uri="tmp/lancedb",
    )

    # Create knowledge base
    knowledge_base = PDFKnowledgeBase(
        path=str(Path(__file__).parent / "data"),
        vector_db=vector_db,
    )

    await knowledge_base.aload(recreate=True)

    assert await vector_db.async_exists()
    assert await vector_db.async_get_count() == 10

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = await agent.arun("What ingredients do I need for Tom Kha Gai?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] == "async_search_knowledge_base"

    assert any(ingredient in response.content.lower() for ingredient in ["coconut", "chicken", "galangal"])

    # Clean up
    await vector_db.async_drop()
