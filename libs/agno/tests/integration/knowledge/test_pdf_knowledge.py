import os
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.lancedb.lance_db import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    path = f"tmp/chromadb_{os.urandom(4).hex()}"
    vector_db = ChromaDb(collection="vectors", path=path, persistent_client=True)
    yield vector_db
    # Clean up after test
    vector_db.drop()


@pytest.fixture
def setup_contents_db():
    """Setup a temporary contents DB for testing."""
    contents_db = SqliteDb("tmp/contentsdb")
    yield contents_db
    # Clean up after test
    os.remove("tmp/contentsdb")


def get_filtered_data_dir():
    """Get the path to the filtered test data directory."""
    return Path(__file__).parent / "data" / "filters"


def prepare_knowledge(setup_vector_db, setup_contents_db):
    """Prepare a knowledge  with filtered data."""
    kb = Knowledge(vector_db=setup_vector_db, contents_db=setup_contents_db)

    # Load with different user IDs and metadata
    kb.insert(
        path=get_filtered_data_dir() / "cv_1.pdf",
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )

    kb.insert(
        path=get_filtered_data_dir() / "cv_2.pdf",
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    return kb


async def aprepare_knowledge(setup_vector_db, setup_contents_db):
    """Prepare a knowledge  with filtered data asynchronously."""
    # Create knowledge
    kb = Knowledge(vector_db=setup_vector_db, contents_db=setup_contents_db)

    # Load documents with different user IDs and metadata
    await kb.ainsert(
        path=get_filtered_data_dir() / "cv_1.pdf",
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )

    await kb.ainsert(
        path=get_filtered_data_dir() / "cv_2.pdf",
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    return kb


def test_pdf_knowledge():
    vector_db = LanceDb(
        table_name="recipes",
        uri="tmp/lancedb",
    )

    # Create a knowledge  with the PDFs from the data/pdfs directory
    knowledge = Knowledge(
        vector_db=vector_db,
    )

    knowledge.insert(path=str(Path(__file__).parent / "data/thai_recipes_short.pdf"))

    assert vector_db.exists()

    # Create and use the agent
    agent = Agent(knowledge=knowledge)
    response = agent.run("Show me how to make Tom Kha Gai", markdown=True)

    tool_calls = []
    assert response.messages is not None
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] == "search_knowledge_base"

    # Clean up
    vector_db.drop()


@pytest.mark.asyncio
async def test_pdf_knowledge_async():
    vector_db = LanceDb(
        table_name="recipes_async",
        uri="tmp/lancedb",
    )

    # Create knowledge
    knowledge = Knowledge(
        vector_db=vector_db,
    )

    await knowledge.ainsert(path=str(Path(__file__).parent / "data/thai_recipes_short.pdf"))

    assert await vector_db.async_exists()

    # Create and use the agent
    agent = Agent(knowledge=knowledge)
    response = await agent.arun("What ingredients do I need for Tom Kha Gai?", markdown=True)

    tool_calls = []
    assert response.messages is not None
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] == "search_knowledge_base"

    assert response.content is not None
    assert any(ingredient in response.content.lower() for ingredient in ["coconut", "chicken", "galangal"])

    # Clean up
    await vector_db.async_drop()


# for the one with new knowledge filter DX- filters at initialization
def test_text_knowledge_with_metadata_path(setup_vector_db):
    """Test loading text files with metadata using the new path structure."""
    kb = Knowledge(
        vector_db=setup_vector_db,
    )

    kb.insert(
        path=str(get_filtered_data_dir() / "cv_1.pdf"),
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )

    kb.insert(
        path=str(get_filtered_data_dir() / "cv_2.pdf"),
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    # Verify documents were loaded with metadata
    agent = Agent(knowledge=kb)
    response = agent.run(
        "Tell me about Jordan Mitchell's experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    assert response.content is not None
    assert (
        "entry" in response.content.lower()
        or "junior" in response.content.lower()
        or "Jordan" in response.content.lower()
    )
    assert "senior developer" not in response.content.lower()


def test_knowledge_with_metadata_path_invalid_filter(setup_vector_db):
    """Test filtering docx knowledge  with invalid filters using the new path structure."""
    kb = Knowledge(
        vector_db=setup_vector_db,
    )

    kb.insert(
        path=str(get_filtered_data_dir() / "cv_1.pdf"),
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )

    kb.insert(
        path=str(get_filtered_data_dir() / "cv_2.pdf"),
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = agent.run("Tell me about the candidate's experience?", markdown=True)
    response_content = response.content.lower()

    assert len(response_content) > 50

    # Check the tool calls to verify the invalid filter was not used
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call for call in tool_calls if call.get("type") == "function" and call["function"]["name"] == "search_knowledge"
    ]

    found_invalid_filters = False
    for call in function_calls:
        call_args = call["function"].get("arguments", "{}")
        if "nonexistent_filter" in call_args:
            found_invalid_filters = True

    assert not found_invalid_filters


# for the one with new knowledge filter DX- filters at load
def test_knowledge_with_valid_filter(setup_vector_db, setup_contents_db):
    """Test filtering knowledge  with valid filters."""
    kb = prepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent with filters for Jordan Mitchell
    agent = Agent(knowledge=kb, knowledge_filters={"user_id": "jordan_mitchell"})

    # Run a query that should only return results from Jordan Mitchell's CV
    response = agent.run("Tell me about the Jordan Mitchell's experience?", markdown=True)

    # Check response content to verify filtering worked
    assert response.content is not None
    response_content = response.content

    # Jordan Mitchell's CV should mention "software engineering intern"
    assert (
        "entry-level" in response_content.lower()
        or "junior" in response_content.lower()
        or "jordan mitchell" in response_content.lower()
    )

    # Should not mention Taylor Brooks' experience as "senior developer"
    assert "senior developer" not in response_content.lower()


def test_knowledge_with_run_level_filter(setup_vector_db, setup_contents_db):
    """Test filtering knowledge  with filters passed at run time."""
    kb = prepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent without filters
    agent = Agent(knowledge=kb)

    # Run a query with filters provided at run time
    response = agent.run(
        "Tell me about Jordan Mitchell experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Should not mention Jordan Mitchell's experience
    assert any(term in response_content for term in ["jordan mitchell", "entry-level", "junior"])


def test_knowledge_filter_override(setup_vector_db, setup_contents_db):
    """Test that run-level filters override agent-level filters."""
    kb = prepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent with jordan_mitchell filter
    agent = Agent(knowledge=kb, knowledge_filters={"user_id": "taylor_brooks"})

    # Run a query with taylor_brooks filter - should override the agent filter
    response = agent.run(
        "Tell me about Jordan Mitchell's experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Should  mention Jordan Mitchell's experience
    assert any(term in response_content for term in ["jordan mitchell", "entry-level", "intern", "junior"])

    # Taylor Brooks' CV should not be used instead of Jordan Mitchell's
    assert not any(term in response_content for term in ["taylor", "brooks", "senior", "developer", "mid level"])


# -- Via URL


@pytest.mark.asyncio
async def test_pdf_url_knowledge_base_async():
    vector_db = LanceDb(
        table_name="recipes_async",
        uri="tmp/lancedb",
    )

    # Create knowledge base
    knowledge = Knowledge(
        vector_db=vector_db,
    )

    await knowledge.ainsert_many(
        urls=[
            "https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
            "https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        ]
    )
    assert await vector_db.async_exists()
    assert await vector_db.async_get_count() > 1

    # Create and use the agent
    agent = Agent(knowledge=knowledge)
    response = await agent.arun("What ingredients do I need for Tom Kha Gai?", markdown=True)

    tool_calls = []
    assert response.messages is not None
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] == "search_knowledge_base"

    assert response.content is not None
    assert any(ingredient in response.content.lower() for ingredient in ["coconut", "chicken", "galangal"])

    # Clean up
    await vector_db.async_drop()


# for the one with new knowledge filter DX- filters at initialize
@pytest.mark.asyncio
async def test_pdf_url_knowledge_base_with_metadata_path(setup_vector_db):
    """Test loading PDF URLs with metadata using the new path structure."""
    kb = Knowledge(
        vector_db=setup_vector_db,
    )

    await kb.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        metadata={"cuisine": "Thai", "source": "Thai Cookbook", "region": "Southeast Asia"},
    )

    await kb.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
        metadata={"cuisine": "Cape", "source": "Cape Cookbook", "region": "South Africa"},
    )

    # Verify documents were loaded with metadata
    agent = Agent(knowledge=kb)
    response = agent.run("Tell me about Thai recipes", knowledge_filters={"cuisine": "Thai"}, markdown=True)

    assert response.content is not None
    response_content = response.content.lower()

    # Thai cuisine recipe should mention Thai ingredients or dishes
    assert any(term in response_content for term in ["tom kha", "pad thai", "thai cuisine", "coconut milk"])
    # Should not mention Cape cuisine terms
    assert not any(term in response_content for term in ["cape malay", "bobotie", "south african"])


def test_pdf_url_knowledge_base_with_metadata_path_invalid_filter(setup_vector_db, setup_contents_db):
    """Test loading PDF URLs with metadata using the new path structure and invalid filters."""
    kb = Knowledge(
        vector_db=setup_vector_db,
        contents_db=setup_contents_db,
    )

    kb.insert(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        metadata={"cuisine": "Thai", "source": "Thai Cookbook", "region": "Southeast Asia"},
    )

    kb.insert(
        url="https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
        metadata={"cuisine": "Cape", "source": "Cape Cookbook", "region": "South Africa"},
    )

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = agent.run("Tell me about the recipes available", markdown=True)
    assert response.content is not None
    response_content = response.content.lower()

    # Check that we have a substantive response
    assert len(response_content) > 50

    # The response should either ask for clarification or mention recipes
    clarification_phrases = [
        "specify",
        "which cuisine",
        "please clarify",
        "need more information",
        "be more specific",
        "specific",
    ]

    recipes_mentioned = any(cuisine in response_content for cuisine in ["thai", "cape", "tom kha", "cape malay"])
    valid_response = any(phrase in response_content for phrase in clarification_phrases) or recipes_mentioned

    # Print debug information
    print(f"Response content: {response_content}")
    print(f"Contains clarification phrase: {any(phrase in response_content for phrase in clarification_phrases)}")
    print(f"Recipes mentioned: {recipes_mentioned}")

    assert valid_response

    # Verify that invalid filter was not used in tool calls
    tool_calls = []
    assert response.messages is not None
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "search_knowledge_base"
    ]

    # Check if any of the search_knowledge_base calls had the invalid filter
    found_invalid_filters = False
    for call in function_calls:
        call_args = call["function"].get("arguments", "{}")
        if "nonexistent_filter" in call_args:
            found_invalid_filters = True

    # Assert that the invalid filter was not used in the actual calls
    assert not found_invalid_filters


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_metadata_path(setup_vector_db):
    """Test async loading of PDF URLs with metadata using the new path structure."""
    kb = Knowledge(
        vector_db=setup_vector_db,
    )

    await kb.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        metadata={"cuisine": "Thai", "source": "Thai Cookbook", "region": "Southeast Asia"},
    )
    await kb.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
        metadata={"cuisine": "Cape", "source": "Cape Cookbook", "region": "South Africa"},
    )

    agent = Agent(knowledge=kb)
    response = await agent.arun("Tell me about Thai recipes", knowledge_filters={"cuisine": "Thai"}, markdown=True)

    assert response.content is not None
    response_content = response.content.lower()

    # Thai cuisine recipe should mention Thai ingredients or dishes
    assert any(term in response_content for term in ["tom kha", "pad thai", "thai cuisine", "coconut milk"])
    # Should not mention Cape cuisine terms
    assert not any(term in response_content for term in ["cape malay", "bobotie", "south african"])


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_metadata_path_invalid_filter(setup_vector_db, setup_contents_db):
    """Test async loading of PDF URLs with metadata using the new path structure and invalid filters."""
    kb = Knowledge(
        vector_db=setup_vector_db,
        contents_db=setup_contents_db,
    )

    await kb.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        metadata={"cuisine": "Thai", "source": "Thai Cookbook", "region": "Southeast Asia"},
    )
    await kb.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
        metadata={"cuisine": "Cape", "source": "Cape Cookbook", "region": "South Africa"},
    )

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = await agent.arun("Tell me about the recipes available", markdown=True)
    assert response.content is not None
    response_content = response.content.lower()

    # Check that we have a substantive response
    assert len(response_content) > 50

    # The response should either ask for clarification or mention recipes
    clarification_phrases = [
        "specify",
        "which cuisine",
        "please clarify",
        "need more information",
        "be more specific",
        "specific",
    ]

    recipes_mentioned = any(cuisine in response_content for cuisine in ["thai", "cape", "tom kha", "cape malay"])
    valid_response = any(phrase in response_content for phrase in clarification_phrases) or recipes_mentioned

    # Print debug information
    print(f"Response content: {response_content}")
    print(f"Contains clarification phrase: {any(phrase in response_content for phrase in clarification_phrases)}")
    print(f"Recipes mentioned: {recipes_mentioned}")

    assert valid_response

    # Verify that invalid filter was not used in tool calls
    tool_calls = []
    assert response.messages is not None
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "search_knowledge_base"
    ]

    # Check if any of the search_knowledge_base calls had the invalid filter
    found_invalid_filters = False
    for call in function_calls:
        call_args = call["function"].get("arguments", "{}")
        if "nonexistent_filter" in call_args:
            found_invalid_filters = True

    # Assert that the invalid filter was not used in the actual calls
    assert not found_invalid_filters


# for the one with new knowledge filter DX - filters at load
def test_pdf_url_knowledge_base_with_valid_filter(setup_vector_db, setup_contents_db):
    """Test filtering PDF URL knowledge base with valid filters."""
    kb = prepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent with filters for Thai cuisine
    agent = Agent(knowledge=kb, knowledge_filters={"cuisine": "Thai"})

    # Run a query that should only return results from Thai cuisine
    response = agent.run("Tell me about Tom Kha Gai recipe", markdown=True)

    # Check response content to verify filtering worked
    assert response.content is not None
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Thai cuisine recipe should mention coconut milk, galangal, or other Thai ingredients
    assert any(term in response_content for term in ["coconut milk", "galangal", "lemongrass", "tom kha"])

    # Should not mention Cape Malay curry or bobotie (Cape cuisine)
    assert not any(term in response_content for term in ["cape malay curry", "bobotie", "apricot jam"])


def test_pdf_url_knowledge_base_with_run_level_filter(setup_vector_db, setup_contents_db):
    """Test filtering PDF URL knowledge base with filters passed at run time."""
    kb = prepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent without filters
    agent = Agent(knowledge=kb)

    # Run a query with filters provided at run time
    response = agent.run("Tell me about Cape Malay curry recipe", knowledge_filters={"cuisine": "Cape"}, markdown=True)

    # Check response content to verify filtering worked
    assert response.content is not None
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Cape cuisine recipe should mention Cape Malay curry or related terms
    assert any(term in response_content for term in ["cape malay", "curry", "turmeric", "cinnamon"])

    # Should not mention Thai recipes like Pad Thai or Tom Kha Gai
    assert not any(term in response_content for term in ["pad thai", "tom kha gai", "galangal"])


def test_pdf_url_knowledge_base_with_invalid_filter(setup_vector_db, setup_contents_db):
    """Test filtering PDF URL knowledge base with invalid filters."""
    kb = prepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = agent.run("Tell me about recipes in the document", markdown=True)

    assert response.content is not None
    response_content = response.content.lower()

    assert len(response_content) > 50

    # Check the tool calls to verify the invalid filter was not used
    tool_calls = []
    assert response.messages is not None
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "search_knowledge_base"
    ]

    # Check if any of the search_knowledge_base calls had the invalid filter
    found_invalid_filters = False
    for call in function_calls:
        call_args = call["function"].get("arguments", "{}")
        if "nonexistent_filter" in call_args:
            found_invalid_filters = True

    # Assert that the invalid filter was not used in the actual calls
    assert not found_invalid_filters


def test_pdf_url_knowledge_base_filter_override(setup_vector_db, setup_contents_db):
    """Test that run-level filters override agent-level filters."""
    kb = prepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent with Cape cuisine filter
    agent = Agent(knowledge=kb, knowledge_filters={"cuisine": "Cape"})

    # Run a query with Thai cuisine filter - should override the agent filter
    response = agent.run("Tell me about how to make Pad Thai", knowledge_filters={"cuisine": "Thai"}, markdown=True)

    # Check response content to verify filtering worked
    assert response.content is not None
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Thai cuisine should be mentioned instead of Cape cuisine
    assert any(term in response_content for term in ["thai", "tom kha", "pad thai", "lemongrass"])

    # Cape cuisine should not be mentioned
    assert not any(term in response_content for term in ["cape malay", "bobotie", "apricot"])


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_valid_filter(setup_vector_db, setup_contents_db):
    """Test asynchronously filtering PDF URL knowledge base with valid filters."""
    kb = await aprepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent with filters for Thai cuisine
    agent = Agent(knowledge=kb, knowledge_filters={"cuisine": "Thai"})

    # Run a query that should only return results from Thai cuisine
    response = await agent.arun("Tell me about Tom Kha Gai recipe", markdown=True)

    # Check response content to verify filtering worked
    assert response.content is not None
    response_content = response.content.lower()  # type: ignore

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Thai cuisine recipe should mention coconut milk, galangal, or other Thai ingredients
    assert any(term in response_content for term in ["coconut milk", "galangal", "lemongrass", "tom kha"])

    # Should not mention Cape Malay curry or bobotie (Cape cuisine)
    assert not any(term in response_content for term in ["cape malay curry", "bobotie", "apricot jam"])


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_run_level_filter(setup_vector_db, setup_contents_db):
    """Test asynchronously filtering PDF URL knowledge base with filters passed at run time."""
    kb = await aprepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent without filters
    agent = Agent(knowledge=kb)

    # Run a query with filters provided at run time
    response = await agent.arun(
        "Tell me about Cape Malay curry recipe", knowledge_filters={"cuisine": "Cape"}, markdown=True
    )

    # Check response content to verify filtering worked
    assert response.content is not None
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Cape cuisine recipe should mention Cape Malay curry or related terms
    assert any(term in response_content for term in ["cape malay", "curry", "turmeric", "cinnamon"])

    # Should not mention Thai recipes like Pad Thai or Tom Kha Gai
    assert not any(term in response_content for term in ["pad thai", "tom kha gai", "galangal"])


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_invalid_filter(setup_vector_db, setup_contents_db):
    """Test asynchronously filtering PDF URL knowledge base with invalid filters."""
    kb = await aprepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = await agent.arun("Tell me about recipes in the document", markdown=True)

    assert response.content is not None
    response_content = response.content.lower()

    assert len(response_content) > 50

    # Check the tool calls to verify the invalid filter was not used
    tool_calls = []
    assert response.messages is not None
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "search_knowledge_base"
    ]

    # Check if any of the search_knowledge_base calls had the invalid filter
    found_invalid_filters = False
    for call in function_calls:
        call_args = call["function"].get("arguments", "{}")
        if "nonexistent_filter" in call_args:
            found_invalid_filters = True

    # Assert that the invalid filter was not used in the actual calls
    assert not found_invalid_filters


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_filter_override(setup_vector_db, setup_contents_db):
    """Test that run-level filters override agent-level filters in async mode."""
    kb = await aprepare_knowledge(setup_vector_db, setup_contents_db)

    # Initialize agent with Cape cuisine filter
    agent = Agent(knowledge=kb, knowledge_filters={"cuisine": "Cape"})

    # Run a query with Thai cuisine filter - should override the agent filter
    response = await agent.arun("Tell me how to make Pad thai", knowledge_filters={"cuisine": "Thai"}, markdown=True)

    # Check response content to verify filtering worked
    assert response.content is not None
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Thai cuisine should be mentioned instead of Cape cuisine
    assert any(term in response_content for term in ["thai", "tom kha", "pad thai", "lemongrass"])

    # Cape cuisine should not be mentioned
    assert not any(term in response_content for term in ["cape malay", "bobotie", "apricot"])
