import pytest

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
async def test_pdf_url_knowledge_base_async():
    vector_db = LanceDb(
        table_name="recipes_async",
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

    await knowledge_base.aload(recreate=True)

    assert await vector_db.async_exists()
    assert await vector_db.async_get_count() == 13  # 3 from first pdf and 10 from second pdf

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
