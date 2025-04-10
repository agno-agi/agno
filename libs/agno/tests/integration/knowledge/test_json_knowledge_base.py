from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.json import JSONKnowledgeBase
from agno.vectordb.lancedb.lance_db import LanceDb


def test_json_knowledge_base():
    vector_db = LanceDb(
        table_name="recipes_json",
        uri="tmp/lancedb",
    )

    knowledge_base = JSONKnowledgeBase(
        path=str(Path(__file__).parent / "data/json"),
        vector_db=vector_db,
    )

    knowledge_base.load(recreate=True)

    assert vector_db.exists()

    # We have 2 JSON files with 3 and 2 documents respectively
    expected_docs = 5
    assert vector_db.get_count() == expected_docs

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = agent.run("Tell me about Thai curry recipes", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] == "search_knowledge_base"

    # Clean up
    vector_db.drop()


def test_json_knowledge_base_single_file():
    vector_db = LanceDb(
        table_name="recipes_json_single",
        uri="tmp/lancedb",
    )

    # Create a knowledge base with a single JSON file
    knowledge_base = JSONKnowledgeBase(
        path=str(Path(__file__).parent / "data/json/recipes.json"),
        vector_db=vector_db,
    )

    knowledge_base.load(recreate=True)

    assert vector_db.exists()

    # The recipes.json file contains 3 documents
    expected_docs = 3
    assert vector_db.get_count() == expected_docs

    # Clean up
    vector_db.drop()


@pytest.mark.asyncio
async def test_json_knowledge_base_async():
    vector_db = LanceDb(
        table_name="recipes_json_async",
        uri="tmp/lancedb",
    )

    # Create knowledge base
    knowledge_base = JSONKnowledgeBase(
        path=str(Path(__file__).parent / "data/json"),
        vector_db=vector_db,
    )

    await knowledge_base.aload(recreate=True)

    assert await vector_db.async_exists()

    # We have 2 JSON files with 3 and 2 documents respectively
    expected_docs = 5
    assert await vector_db.async_get_count() == expected_docs

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


@pytest.mark.asyncio
async def test_json_knowledge_base_async_single_file():
    vector_db = LanceDb(
        table_name="recipes_json_async_single",
        uri="tmp/lancedb",
    )

    # Create knowledge base with a single JSON file
    knowledge_base = JSONKnowledgeBase(
        path=str(Path(__file__).parent / "data/json/recipes.json"),
        vector_db=vector_db,
    )

    await knowledge_base.aload(recreate=True)

    assert await vector_db.async_exists()

    expected_docs = 3
    assert await vector_db.async_get_count() == expected_docs

    await vector_db.async_drop()
