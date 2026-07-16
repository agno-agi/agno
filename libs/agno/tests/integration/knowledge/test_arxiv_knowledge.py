import pytest

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.arxiv_reader import ArxivReader
from agno.vectordb.chroma import ChromaDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    vector_db = ChromaDb(collection="vectors", path="tmp/chromadb", persistent_client=True)
    yield vector_db
    # Clean up after test
    vector_db.drop()


def test_arxiv_knowledge_base_integration(setup_vector_db):
    """Integration test using real arXiv papers."""
    reader = ArxivReader(
        max_results=1,  # Limit to exactly one result per query
    )
    knowledge = Knowledge(
        vector_db=setup_vector_db,
    )

    knowledge.insert(
        metadata={"user_tag": "Arxiv content"},
        # "Attention Is All You Need" and "BERT" papers
        topics=["1706.03762", "1810.04805"],
        reader=reader,
    )

    assert setup_vector_db.exists()
    # Check that we have at least the papers we requested
    assert setup_vector_db.get_count() >= 2

    agent = Agent(knowledge=knowledge)
    response = agent.run("Explain the key concepts of transformer architecture", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_arxiv_knowledge_base_search_integration(setup_vector_db):
    """Integration test using real arXiv search query."""
    reader = ArxivReader(
        max_results=3,  # Limit results for testing
    )
    knowledge = Knowledge(
        vector_db=setup_vector_db,
    )

    knowledge.insert(
        metadata={"user_tag": "Arxiv content"},
        topics=["transformer architecture language models"],
        reader=reader,
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=knowledge)
    response = agent.run("What are the recent developments in transformer models?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_arxiv_knowledge_base_async_integration(setup_vector_db):
    """Integration test using real arXiv papers with async loading."""
    reader = ArxivReader()
    knowledge = Knowledge(
        vector_db=setup_vector_db,
        max_results=1,  # Limit to exactly one result per query
    )

    await knowledge.ainsert(
        # "GPT-3" and "AlphaFold" papers
        topics=["2005.14165", "2003.02645"],
        reader=reader,
    )

    assert await setup_vector_db.async_exists()
    # Check that we have at least the papers we requested
    assert setup_vector_db.get_count() >= 2

    agent = Agent(
        knowledge=knowledge,
        search_knowledge=True,
        instructions=[
            "You are a helpful assistant that can answer questions.",
            "You can use the search_knowledge_base tool to search the knowledge base of journal articles for information.",
        ],
    )
    response = await agent.arun("What are the key capabilities of GPT-3?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)
