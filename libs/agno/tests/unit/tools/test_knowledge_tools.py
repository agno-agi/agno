"""Unit tests for KnowledgeTools class."""

import json
from unittest.mock import MagicMock, Mock

import pytest

from agno.knowledge.knowledge import Knowledge
from agno.tools.knowledge import KnowledgeTools


@pytest.fixture
def mock_knowledge():
    """Create a mock Knowledge instance for testing."""
    mock_kb = Mock(spec=Knowledge)
    mock_kb.search = Mock()
    return mock_kb


@pytest.fixture
def knowledge_tools(mock_knowledge):
    """Create KnowledgeTools instance with mocked Knowledge."""
    return KnowledgeTools(
        knowledge=mock_knowledge,
        enable_think=True,
        enable_search=True,
        enable_analyze=True,
    )


def test_knowledge_tools_initialization():
    """Test KnowledgeTools initialization with different settings."""
    mock_knowledge = Mock(spec=Knowledge)

    # Test with all features enabled
    tools = KnowledgeTools(
        knowledge=mock_knowledge,
        enable_think=True,
        enable_search=True,
        enable_analyze=True,
    )

    assert tools.knowledge == mock_knowledge
    # Check that tools are registered with correct names
    tool_names = list(tools.functions.keys())
    assert "think" in tool_names
    assert "search_knowledge" in tool_names
    assert "analyze" in tool_names


def test_knowledge_tools_selective_features():
    """Test KnowledgeTools with selective feature enabling."""
    mock_knowledge = Mock(spec=Knowledge)

    # Test with only search enabled
    tools = KnowledgeTools(
        knowledge=mock_knowledge,
        enable_think=False,
        enable_search=True,
        enable_analyze=False,
    )

    tool_names = list(tools.functions.keys())
    assert "think" not in tool_names
    assert "search_knowledge" in tool_names
    assert "analyze" not in tool_names


def test_search_knowledge_method(knowledge_tools, mock_knowledge):
    """Test the search_knowledge method functionality."""
    # Mock the knowledge.search return value
    mock_doc = Mock()
    mock_doc.to_dict.return_value = {"content": "Test content", "metadata": {"source": "test.txt"}}
    mock_knowledge.search.return_value = [mock_doc]

    # Test successful search
    session_state = {}
    result = knowledge_tools.search_knowledge(session_state, "test query")

    # Verify knowledge.search was called correctly
    mock_knowledge.search.assert_called_once_with(query="test query")

    # Verify result is JSON string containing document data
    result_data = json.loads(result)
    assert len(result_data) == 1
    assert result_data[0]["content"] == "Test content"
    assert result_data[0]["metadata"]["source"] == "test.txt"


def test_search_knowledge_no_results(knowledge_tools, mock_knowledge):
    """Test search_knowledge when no documents are found."""
    mock_knowledge.search.return_value = []

    session_state = {}
    result = knowledge_tools.search_knowledge(session_state, "test query")

    assert result == "No documents found"


def test_search_knowledge_error_handling(knowledge_tools, mock_knowledge):
    """Test search_knowledge error handling."""
    mock_knowledge.search.side_effect = Exception("Search failed")

    session_state = {}
    result = knowledge_tools.search_knowledge(session_state, "test query")

    assert "Error searching knowledge base: Search failed" in result


def test_think_method(knowledge_tools):
    """Test the think method functionality."""
    session_state = {}
    thought = "This is a test thought about analyzing the problem."

    result = knowledge_tools.think(session_state, thought)

    # Should return the formatted thought
    assert "This is a test thought about analyzing the problem." in result
    assert len(result) > len(thought)  # Should be formatted/expanded


def test_analyze_method(knowledge_tools):
    """Test the analyze method functionality."""
    session_state = {}
    analysis = "This analysis shows that the data indicates a trend."

    result = knowledge_tools.analyze(session_state, analysis)

    # Should return the formatted analysis
    assert "This analysis shows that the data indicates a trend." in result
    assert len(result) > len(analysis)  # Should be formatted/expanded


def test_tool_registration_names():
    """Test that tools are registered with correct names for API compatibility."""
    mock_knowledge = Mock(spec=Knowledge)

    tools = KnowledgeTools(
        knowledge=mock_knowledge,
        enable_think=True,
        enable_search=True,
        enable_analyze=True,
    )

    # Verify the renamed search tool is registered as "search_knowledge"
    tool_names = list(tools.functions.keys())
    assert "search_knowledge" in tool_names
    assert "search" not in tool_names  # Old name should not exist

    # Verify other tools have expected names
    assert "think" in tool_names
    assert "analyze" in tool_names


def test_all_parameter():
    """Test the 'all' parameter enables all tools."""
    mock_knowledge = Mock(spec=Knowledge)

    tools = KnowledgeTools(
        knowledge=mock_knowledge,
        all=True,  # Should enable all tools regardless of individual flags
        enable_think=False,
        enable_search=False,
        enable_analyze=False,
    )

    tool_names = list(tools.functions.keys())
    assert "think" in tool_names
    assert "search_knowledge" in tool_names
    assert "analyze" in tool_names


def test_custom_instructions():
    """Test KnowledgeTools with custom instructions."""
    mock_knowledge = Mock(spec=Knowledge)
    custom_instructions = "Use this knowledge base to answer questions accurately."

    tools = KnowledgeTools(
        knowledge=mock_knowledge,
        instructions=custom_instructions,
        add_instructions=True,
    )

    assert custom_instructions in tools.instructions


def test_few_shot_examples():
    """Test KnowledgeTools with few-shot examples enabled."""
    mock_knowledge = Mock(spec=Knowledge)

    tools = KnowledgeTools(
        knowledge=mock_knowledge,
        add_few_shot=True,
    )

    # Should include few-shot examples in instructions
    assert "Think" in tools.instructions
    assert "Search" in tools.instructions
    assert "Analyze" in tools.instructions


def test_method_existence():
    """Test that renamed methods exist and old ones don't."""
    mock_knowledge = Mock(spec=Knowledge)
    tools = KnowledgeTools(knowledge=mock_knowledge)

    # New method should exist
    assert hasattr(tools, "search_knowledge")
    assert callable(getattr(tools, "search_knowledge"))

    # Other methods should exist
    assert hasattr(tools, "think")
    assert hasattr(tools, "analyze")
