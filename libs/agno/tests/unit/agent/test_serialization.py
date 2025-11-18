import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager
from agno.culture import CultureManager
from agno.session import SessionSummaryManager
from agno.knowledge import Knowledge
import json

from agno.tools.function import Function

def test_basic_agent_serialization():
    """Test basic agent serialization without complex managers."""
    print("Testing basic agent serialization...")
    
    # Create a basic agent
    agent = Agent(
        id="test-agent",
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o"),
        instructions="You are a helpful assistant",
        markdown=True,
        add_datetime_to_context=True,
        add_history_to_context=True,
        enable_agentic_memory=False,
    )
    
    # Serialize to dict
    config_dict = agent.to_dict()
    
    # Verify JSON serializable
    json_str = json.dumps(config_dict, indent=2)
    assert json_str is not None
    
    # Reconstruct agent from dict
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent is not None

    # Verify key attributes match
    assert reconstructed_agent.name == agent.name, "Name mismatch"
    assert reconstructed_agent.id == agent.id, "ID mismatch"
    assert reconstructed_agent.markdown == agent.markdown, "Markdown mismatch"
    assert reconstructed_agent.add_datetime_to_context == agent.add_datetime_to_context, "Context setting mismatch"
    

def test_agent_with_tools_serialization():
    """Test agent serialization with tools."""
    print("\nTesting agent with tools serialization...")
    
    # Create agent with tools
    agent = Agent(
        id="tool-agent",
        name="Tool Agent",
        model=OpenAIChat(id="gpt-4o"),
        tools=[DuckDuckGoTools()],
        instructions="You are a web search agent",
        tool_call_limit=5,
    )
    
    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    
    for tool in reconstructed_agent.tools:
        assert isinstance(tool, Function)
    
