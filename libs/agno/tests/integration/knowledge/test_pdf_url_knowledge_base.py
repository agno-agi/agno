import os

import pytest

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.lancedb.lance_db import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a vector database for testing."""
    # Generate a unique table name to avoid conflicts between tests
    table_name = f"pdf-url-filter-test-{os.urandom(4).hex()}"
    vector_db = LanceDb(
        table_name=table_name,
        uri="tmp/lancedb",
    )
    yield vector_db
    # Clean up
    vector_db.drop()


def prepare_knowledge_base(vector_db):
    """Prepare a PDF URL knowledge base with test data."""
    # Create knowledge base
    knowledge_base = PDFUrlKnowledgeBase(
        vector_db=vector_db,
    )

    # Load Thai recipes PDF with Thai cuisine metadata
    knowledge_base.load_document(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        metadata={"cuisine": "Thai", "source": "Thai Cookbook"},
        recreate=True,
    )

    # Load Cape recipes PDF with Cape cuisine metadata
    knowledge_base.load_document(
        url="https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
        metadata={"cuisine": "Cape", "source": "Cape Cookbook"},
    )

    return knowledge_base


async def aprepare_knowledge_base(vector_db):
    """Asynchronously prepare a PDF URL knowledge base with test data."""
    # Create knowledge base
    knowledge_base = PDFUrlKnowledgeBase(
        vector_db=vector_db,
    )

    # Load Thai recipes PDF with Thai cuisine metadata
    await knowledge_base.aload_document(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        metadata={"cuisine": "Thai", "source": "Thai Cookbook"},
        recreate=True,
    )

    # Load Cape recipes PDF with Cape cuisine metadata
    await knowledge_base.aload_document(
        url="https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
        metadata={"cuisine": "Cape", "source": "Cape Cookbook"},
    )

    return knowledge_base


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
            assert call["function"]["name"] == "asearch_knowledge_base"

    assert any(ingredient in response.content.lower() for ingredient in ["coconut", "chicken", "galangal"])

    # Clean up
    await vector_db.async_drop()


# for the one with new knowledge filter DX- filters at initialize
def test_pdf_url_knowledge_base_with_metadata_path(setup_vector_db):
    """Test loading PDF URLs with metadata using the new path structure."""
    kb = PDFUrlKnowledgeBase(
        urls=[
            {
                "url": "https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
                "metadata": {"cuisine": "Thai", "source": "Thai Cookbook", "region": "Southeast Asia"},
            },
            {
                "url": "https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
                "metadata": {"cuisine": "Cape", "source": "Cape Cookbook", "region": "South Africa"},
            },
        ],
        vector_db=setup_vector_db,
    )

    kb.load(recreate=True)

    # Verify documents were loaded with metadata
    agent = Agent(knowledge=kb)
    response = agent.run("Tell me about Thai recipes", knowledge_filters={"cuisine": "Thai"}, markdown=True)

    response_content = response.content.lower()

    # Thai cuisine recipe should mention Thai ingredients or dishes
    assert any(term in response_content for term in ["tom kha", "pad thai", "thai cuisine", "coconut milk"])
    # Should not mention Cape cuisine terms
    assert not any(term in response_content for term in ["cape malay", "bobotie", "south african"])


def test_pdf_url_knowledge_base_with_metadata_path_invalid_filter(setup_vector_db):
    """Test loading PDF URLs with metadata using the new path structure and invalid filters."""
    kb = PDFUrlKnowledgeBase(
        urls=[
            {
                "url": "https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
                "metadata": {"cuisine": "Thai", "source": "Thai Cookbook", "region": "Southeast Asia"},
            },
            {
                "url": "https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
                "metadata": {"cuisine": "Cape", "source": "Cape Cookbook", "region": "South Africa"},
            },
        ],
        vector_db=setup_vector_db,
    )

    kb.load(recreate=True)

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = agent.run("Tell me about the recipes available", markdown=True)
    response_content = response.content.lower()

    # Check that we have a substantive response
    assert len(response_content) > 50

    # The response should either ask for clarification or mention recipes
    clarification_phrases = [
        "specify which",
        "which cuisine",
        "please clarify",
        "need more information",
        "be more specific",
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
    kb = PDFUrlKnowledgeBase(
        urls=[
            {
                "url": "https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
                "metadata": {"cuisine": "Thai", "source": "Thai Cookbook", "region": "Southeast Asia"},
            },
            {
                "url": "https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
                "metadata": {"cuisine": "Cape", "source": "Cape Cookbook", "region": "South Africa"},
            },
        ],
        vector_db=setup_vector_db,
    )

    await kb.aload(recreate=True)

    agent = Agent(knowledge=kb)
    response = await agent.arun("Tell me about Thai recipes", knowledge_filters={"cuisine": "Thai"}, markdown=True)

    response_content = response.content.lower()

    # Thai cuisine recipe should mention Thai ingredients or dishes
    assert any(term in response_content for term in ["tom kha", "pad thai", "thai cuisine", "coconut milk"])
    # Should not mention Cape cuisine terms
    assert not any(term in response_content for term in ["cape malay", "bobotie", "south african"])


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_metadata_path_invalid_filter(setup_vector_db):
    """Test async loading of PDF URLs with metadata using the new path structure and invalid filters."""
    kb = PDFUrlKnowledgeBase(
        urls=[
            {
                "url": "https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
                "metadata": {"cuisine": "Thai", "source": "Thai Cookbook", "region": "Southeast Asia"},
            },
            {
                "url": "https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
                "metadata": {"cuisine": "Cape", "source": "Cape Cookbook", "region": "South Africa"},
            },
        ],
        vector_db=setup_vector_db,
    )

    await kb.aload(recreate=True)

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = await agent.arun("Tell me about the recipes available", markdown=True)
    response_content = response.content.lower()

    # Check that we have a substantive response
    assert len(response_content) > 50

    # The response should either ask for clarification or mention recipes
    clarification_phrases = [
        "specify which",
        "which cuisine",
        "please clarify",
        "need more information",
        "be more specific",
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
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "asearch_knowledge_base"
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
def test_pdf_url_knowledge_base_with_valid_filter(setup_vector_db):
    """Test filtering PDF URL knowledge base with valid filters."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent with filters for Thai cuisine
    agent = Agent(knowledge=kb, knowledge_filters={"cuisine": "Thai"})

    # Run a query that should only return results from Thai cuisine
    response = agent.run("Tell me about Tom Kha Gai recipe", markdown=True)

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Thai cuisine recipe should mention coconut milk, galangal, or other Thai ingredients
    assert any(term in response_content for term in ["coconut milk", "galangal", "lemongrass", "tom kha"])

    # Should not mention Cape Malay curry or bobotie (Cape cuisine)
    assert not any(term in response_content for term in ["cape malay curry", "bobotie", "apricot jam"])


def test_pdf_url_knowledge_base_with_run_level_filter(setup_vector_db):
    """Test filtering PDF URL knowledge base with filters passed at run time."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent without filters
    agent = Agent(knowledge=kb)

    # Run a query with filters provided at run time
    response = agent.run("Tell me about Cape Malay curry recipe", knowledge_filters={"cuisine": "Cape"}, markdown=True)

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Cape cuisine recipe should mention Cape Malay curry or related terms
    assert any(term in response_content for term in ["cape malay", "curry", "turmeric", "cinnamon"])

    # Should not mention Thai recipes like Pad Thai or Tom Kha Gai
    assert not any(term in response_content for term in ["pad thai", "tom kha gai", "galangal"])


def test_pdf_url_knowledge_base_with_invalid_filter(setup_vector_db):
    """Test filtering PDF URL knowledge base with invalid filters."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = agent.run("Tell me about recipes in the document", markdown=True)

    response_content = response.content.lower()

    assert len(response_content) > 50

    clarification_phrases = [
        "specify which",
        "which cuisine",
        "please clarify",
        "need more information",
        "be more specific",
    ]

    cuisines_mentioned = any(cuisine in response_content for cuisine in ["thai", "cape", "tom kha", "cape malay"])

    valid_response = any(phrase in response_content for phrase in clarification_phrases) or cuisines_mentioned

    # Print response content for debugging
    print(f"Response content: {response_content}")
    print(f"Contains clarification phrase: {any(phrase in response_content for phrase in clarification_phrases)}")
    print(f"Cuisines mentioned: {cuisines_mentioned}")

    assert valid_response

    # Check the tool calls to verify the invalid filter was not used
    tool_calls = []
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


def test_pdf_url_knowledge_base_filter_override(setup_vector_db):
    """Test that run-level filters override agent-level filters."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent with Cape cuisine filter
    agent = Agent(knowledge=kb, knowledge_filters={"cuisine": "Cape"})

    # Run a query with Thai cuisine filter - should override the agent filter
    response = agent.run("Tell me about how to make Pad Thai", knowledge_filters={"cuisine": "Thai"}, markdown=True)

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Thai cuisine should be mentioned instead of Cape cuisine
    assert any(term in response_content for term in ["thai", "tom kha", "pad thai", "lemongrass"])

    # Cape cuisine should not be mentioned
    assert not any(term in response_content for term in ["cape malay", "bobotie", "apricot"])


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_valid_filter(setup_vector_db):
    """Test asynchronously filtering PDF URL knowledge base with valid filters."""
    kb = await aprepare_knowledge_base(setup_vector_db)

    # Initialize agent with filters for Thai cuisine
    agent = Agent(knowledge=kb, knowledge_filters={"cuisine": "Thai"})

    # Run a query that should only return results from Thai cuisine
    response = await agent.arun("Tell me about Tom Kha Gai recipe", markdown=True)

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Thai cuisine recipe should mention coconut milk, galangal, or other Thai ingredients
    assert any(term in response_content for term in ["coconut milk", "galangal", "lemongrass", "tom kha"])

    # Should not mention Cape Malay curry or bobotie (Cape cuisine)
    assert not any(term in response_content for term in ["cape malay curry", "bobotie", "apricot jam"])


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_run_level_filter(setup_vector_db):
    """Test asynchronously filtering PDF URL knowledge base with filters passed at run time."""
    kb = await aprepare_knowledge_base(setup_vector_db)

    # Initialize agent without filters
    agent = Agent(knowledge=kb)

    # Run a query with filters provided at run time
    response = await agent.arun(
        "Tell me about Cape Malay curry recipe", knowledge_filters={"cuisine": "Cape"}, markdown=True
    )

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Cape cuisine recipe should mention Cape Malay curry or related terms
    assert any(term in response_content for term in ["cape malay", "curry", "turmeric", "cinnamon"])

    # Should not mention Thai recipes like Pad Thai or Tom Kha Gai
    assert not any(term in response_content for term in ["pad thai", "tom kha gai", "galangal"])


@pytest.mark.asyncio
async def test_async_pdf_url_knowledge_base_with_invalid_filter(setup_vector_db):
    """Test asynchronously filtering PDF URL knowledge base with invalid filters."""
    kb = await aprepare_knowledge_base(setup_vector_db)

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = await agent.arun("Tell me about recipes in the document", markdown=True)

    response_content = response.content.lower()

    assert len(response_content) > 50

    clarification_phrases = [
        "specify which",
        "which cuisine",
        "please clarify",
        "need more information",
        "be more specific",
    ]

    cuisines_mentioned = any(cuisine in response_content for cuisine in ["thai", "cape", "tom kha", "cape malay"])

    valid_response = any(phrase in response_content for phrase in clarification_phrases) or cuisines_mentioned

    # Print response content for debugging
    print(f"Response content: {response_content}")
    print(f"Contains clarification phrase: {any(phrase in response_content for phrase in clarification_phrases)}")
    print(f"Cuisines mentioned: {cuisines_mentioned}")

    assert valid_response

    # Check the tool calls to verify the invalid filter was not used
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "asearch_knowledge_base"
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
async def test_async_pdf_url_knowledge_base_filter_override(setup_vector_db):
    """Test that run-level filters override agent-level filters in async mode."""
    kb = await aprepare_knowledge_base(setup_vector_db)

    # Initialize agent with Cape cuisine filter
    agent = Agent(knowledge=kb, knowledge_filters={"cuisine": "Cape"})

    # Run a query with Thai cuisine filter - should override the agent filter
    response = await agent.arun("Tell me how to make Pad thai", knowledge_filters={"cuisine": "Thai"}, markdown=True)

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Thai cuisine should be mentioned instead of Cape cuisine
    assert any(term in response_content for term in ["thai", "tom kha", "pad thai", "lemongrass"])

    # Cape cuisine should not be mentioned
    assert not any(term in response_content for term in ["cape malay", "bobotie", "apricot"])
