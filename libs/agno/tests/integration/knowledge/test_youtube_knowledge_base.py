import os

import pytest

from agno.agent import Agent
from agno.knowledge.youtube import YouTubeKnowledgeBase
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"youtube_test_{os.urandom(4).hex()}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    vector_db.drop()


@pytest.mark.skip(reason="They block requests from CI")
def test_youtube_knowledge_base_directory(setup_vector_db):
    """Test loading multiple YouTube videos into the knowledge base."""
    urls = ["https://www.youtube.com/watch?v=NwZ26lxl8wU", "https://www.youtube.com/watch?v=lrg8ZWI7MCg"]

    kb = YouTubeKnowledgeBase(urls=urls, vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run(
        "What is the major focus of the knowledge provided in both the videos, explain briefly.", markdown=True
    )

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    print(f"Function calls: {function_calls}")
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.skip(reason="They block requests from CI")
def test_youtube_knowledge_base_single_url(setup_vector_db):
    """Test loading a single YouTube video into the knowledge base."""
    kb = YouTubeKnowledgeBase(
        urls=["https://www.youtube.com/watch?v=NwZ26lxl8wU"],
        vector_db=setup_vector_db,
    )
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(
        knowledge=kb,
        search_knowledge=True,
        instructions=[
            "You are a helpful assistant that can answer questions about the video.",
            "You can use the search_knowledge_base tool to search the knowledge base of videos for information.",
        ],
    )
    response = agent.run("What is the major focus of the knowledge provided in the video?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.skip(reason="They block requests from CI")
@pytest.mark.asyncio
async def test_youtube_knowledge_base_async_directory(setup_vector_db):
    """Test asynchronously loading multiple YouTube videos."""
    urls = ["https://www.youtube.com/watch?v=NwZ26lxl8wU", "https://www.youtube.com/watch?v=lrg8ZWI7MCg"]

    kb = YouTubeKnowledgeBase(urls=urls, vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    agent = Agent(
        knowledge=kb,
        search_knowledge=True,
        instructions=[
            "You are a helpful assistant that can answer questions about the video.",
            "You can use the search_knowledge_base tool to search the knowledge base of videos for information.",
        ],
    )
    response = await agent.arun(
        "What is the major focus of the knowledge provided in both the videos, explain briefly.", markdown=True
    )

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    assert "asearch_knowledge_base" in [
        call["function"]["name"] for call in tool_calls if call.get("type") == "function"
    ]


@pytest.mark.skip(reason="They block requests from CI")
@pytest.mark.asyncio
async def test_youtube_knowledge_base_async_single_url(setup_vector_db):
    """Test asynchronously loading a single YouTube video."""
    kb = YouTubeKnowledgeBase(urls=["https://www.youtube.com/watch?v=lrg8ZWI7MCg"], vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    agent = Agent(
        knowledge=kb,
        search_knowledge=True,  # Keep for async
        instructions=[
            "You are a helpful assistant that can answer questions about the video.",
            "You can use the search_knowledge_base tool to search the knowledge base of videos for information.",
        ],
    )
    response = await agent.arun("What is the major focus of the knowledge provided in the video?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    assert "asearch_knowledge_base" in [
        call["function"]["name"] for call in tool_calls if call.get("type") == "function"
    ]


def test_youtube_knowledge_base_empty_urls(setup_vector_db):
    """Test loading with empty URL list."""
    kb = YouTubeKnowledgeBase(urls=[], vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 0
