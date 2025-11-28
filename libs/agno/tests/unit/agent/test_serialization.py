import json

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
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
    assert reconstructed_agent.add_history_to_context == agent.add_history_to_context, "History context mismatch"


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

    # Verify tools are reconstructed
    assert reconstructed_agent.tools is not None
    assert len(reconstructed_agent.tools) > 0
    for tool in reconstructed_agent.tools:
        assert isinstance(tool, Function)

    # Verify tool_call_limit
    assert reconstructed_agent.tool_call_limit == agent.tool_call_limit


def test_agent_with_introduction_serialization():
    """Test agent serialization with introduction."""
    print("\nTesting agent with introduction serialization...")

    agent = Agent(
        id="intro-agent",
        name="Intro Agent",
        model=OpenAIChat(id="gpt-4o"),
        introduction="Hello, I'm a helpful assistant!",
        instructions="You are helpful",
    )

    # Serialize
    config_dict = agent.to_dict()
    assert "introduction" in config_dict

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.introduction == agent.introduction


def test_agent_with_session_settings_serialization():
    """Test agent serialization with session settings."""
    print("\nTesting agent with session settings serialization...")

    agent = Agent(
        id="session-agent",
        name="Session Agent",
        model=OpenAIChat(id="gpt-4o"),
        session_id="test-session",
        session_state={"key": "value"},
        add_session_state_to_context=True,
        enable_agentic_state=True,
        cache_session=True,
        overwrite_db_session_state=True,
    )

    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.session_id == agent.session_id
    assert reconstructed_agent.session_state == agent.session_state
    assert reconstructed_agent.add_session_state_to_context == agent.add_session_state_to_context
    assert reconstructed_agent.enable_agentic_state == agent.enable_agentic_state
    assert reconstructed_agent.cache_session == agent.cache_session
    assert reconstructed_agent.overwrite_db_session_state == agent.overwrite_db_session_state


def test_agent_with_reasoning_serialization():
    """Test agent serialization with reasoning settings."""
    print("\nTesting agent with reasoning serialization...")

    agent = Agent(
        id="reasoning-agent",
        name="Reasoning Agent",
        model=OpenAIChat(id="gpt-4o"),
        reasoning=True,
        reasoning_model=OpenAIChat(id="gpt-4o-mini"),
        reasoning_min_steps=2,
        reasoning_max_steps=15,
    )

    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.reasoning == agent.reasoning
    assert reconstructed_agent.reasoning_model is not None
    assert reconstructed_agent.reasoning_min_steps == agent.reasoning_min_steps
    assert reconstructed_agent.reasoning_max_steps == agent.reasoning_max_steps


def test_agent_with_parser_output_models_serialization():
    """Test agent serialization with parser and output models."""
    print("\nTesting agent with parser/output models serialization...")

    agent = Agent(
        id="parser-agent",
        name="Parser Agent",
        model=OpenAIChat(id="gpt-4o"),
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        parser_model_prompt="Parse this response",
        output_model=OpenAIChat(id="gpt-4o-mini"),
        output_model_prompt="Format this output",
        parse_response=True,
        structured_outputs=True,
        use_json_mode=True,
    )

    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.parser_model is not None
    assert reconstructed_agent.parser_model_prompt == agent.parser_model_prompt
    assert reconstructed_agent.output_model is not None
    assert reconstructed_agent.output_model_prompt == agent.output_model_prompt
    assert reconstructed_agent.parse_response == agent.parse_response
    assert reconstructed_agent.structured_outputs == agent.structured_outputs
    assert reconstructed_agent.use_json_mode == agent.use_json_mode


def test_agent_with_streaming_settings_serialization():
    """Test agent serialization with streaming settings."""
    print("\nTesting agent with streaming settings serialization...")

    agent = Agent(
        id="streaming-agent",
        name="Streaming Agent",
        model=OpenAIChat(id="gpt-4o"),
        stream=True,
        stream_events=True,
        store_events=True,
    )

    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.stream == agent.stream
    assert reconstructed_agent.stream_events == agent.stream_events
    assert reconstructed_agent.store_events == agent.store_events


def test_agent_with_context_settings_serialization():
    """Test agent serialization with context building settings."""
    print("\nTesting agent with context settings serialization...")

    agent = Agent(
        id="context-agent",
        name="Context Agent",
        model=OpenAIChat(id="gpt-4o"),
        description="A helpful assistant",
        instructions=["Be helpful", "Be concise"],
        expected_output="A clear answer",
        additional_context="Use simple language",
        markdown=True,
        add_name_to_context=True,
        add_datetime_to_context=True,
        add_location_to_context=True,
        timezone_identifier="America/New_York",
        resolve_in_context=True,
    )

    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.description == agent.description
    assert reconstructed_agent.instructions == agent.instructions
    assert reconstructed_agent.expected_output == agent.expected_output
    assert reconstructed_agent.additional_context == agent.additional_context
    assert reconstructed_agent.markdown == agent.markdown
    assert reconstructed_agent.add_name_to_context == agent.add_name_to_context
    assert reconstructed_agent.add_datetime_to_context == agent.add_datetime_to_context
    assert reconstructed_agent.add_location_to_context == agent.add_location_to_context
    assert reconstructed_agent.timezone_identifier == agent.timezone_identifier
    assert reconstructed_agent.resolve_in_context == agent.resolve_in_context


def test_agent_with_retry_settings_serialization():
    """Test agent serialization with retry settings."""
    print("\nTesting agent with retry settings serialization...")

    agent = Agent(
        id="retry-agent",
        name="Retry Agent",
        model=OpenAIChat(id="gpt-4o"),
        retries=5,
        delay_between_retries=2,
        exponential_backoff=True,
    )

    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.retries == agent.retries
    assert reconstructed_agent.delay_between_retries == agent.delay_between_retries
    assert reconstructed_agent.exponential_backoff == agent.exponential_backoff


def test_agent_with_debug_settings_serialization():
    """Test agent serialization with debug settings."""
    print("\nTesting agent with debug settings serialization...")

    agent = Agent(
        id="debug-agent",
        name="Debug Agent",
        model=OpenAIChat(id="gpt-4o"),
        debug_mode=True,
        debug_level=2,
        telemetry=False,
    )

    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.debug_mode == agent.debug_mode
    assert reconstructed_agent.debug_level == agent.debug_level
    assert reconstructed_agent.telemetry == agent.telemetry


def test_agent_with_knowledge_settings_serialization():
    """Test agent serialization with knowledge settings."""
    print("\nTesting agent with knowledge settings serialization...")

    agent = Agent(
        id="knowledge-agent",
        name="Knowledge Agent",
        model=OpenAIChat(id="gpt-4o"),
        knowledge_filters={"category": "science"},
        enable_agentic_knowledge_filters=True,
        add_knowledge_to_context=True,
        search_knowledge=True,
        update_knowledge=True,
        references_format="yaml",
    )

    # Serialize
    config_dict = agent.to_dict()

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.knowledge_filters == agent.knowledge_filters
    assert reconstructed_agent.enable_agentic_knowledge_filters == agent.enable_agentic_knowledge_filters
    assert reconstructed_agent.add_knowledge_to_context == agent.add_knowledge_to_context
    assert reconstructed_agent.search_knowledge == agent.search_knowledge
    assert reconstructed_agent.update_knowledge == agent.update_knowledge
    assert reconstructed_agent.references_format == agent.references_format


def test_agent_with_compression_settings_serialization():
    """Test agent serialization with compression settings."""
    print("\nTesting agent with compression settings serialization...")

    agent = Agent(
        id="compression-agent",
        name="Compression Agent",
        model=OpenAIChat(id="gpt-4o"),
        compress_tool_results=True,
    )

    # Serialize
    config_dict = agent.to_dict()
    assert "compress_tool_results" in config_dict

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)
    assert reconstructed_agent.compress_tool_results == agent.compress_tool_results


def test_agent_complete_round_trip():
    """Test complete serialization round trip with many settings."""
    print("\nTesting complete agent round trip...")

    agent = Agent(
        id="complete-agent",
        name="Complete Agent",
        introduction="Welcome!",
        model=OpenAIChat(id="gpt-4o"),
        user_id="user-123",
        session_id="session-456",
        instructions="Be helpful and detailed",
        markdown=True,
        description="A comprehensive test agent",
        add_datetime_to_context=True,
        add_name_to_context=True,
        tool_call_limit=10,
        reasoning=True,
        stream=True,
        debug_mode=True,
        metadata={"version": "1.0", "env": "test"},
    )

    # Serialize
    config_dict = agent.to_dict()

    # Verify JSON serializable
    json_str = json.dumps(config_dict, indent=2)
    assert json_str is not None

    # Reconstruct
    reconstructed_agent = Agent.from_dict(config_dict)

    # Verify all key attributes
    assert reconstructed_agent.id == agent.id
    assert reconstructed_agent.name == agent.name
    assert reconstructed_agent.introduction == agent.introduction
    assert reconstructed_agent.user_id == agent.user_id
    assert reconstructed_agent.session_id == agent.session_id
    assert reconstructed_agent.instructions == agent.instructions
    assert reconstructed_agent.markdown == agent.markdown
    assert reconstructed_agent.description == agent.description
    assert reconstructed_agent.add_datetime_to_context == agent.add_datetime_to_context
    assert reconstructed_agent.add_name_to_context == agent.add_name_to_context
    assert reconstructed_agent.tool_call_limit == agent.tool_call_limit
    assert reconstructed_agent.reasoning == agent.reasoning
    assert reconstructed_agent.stream == agent.stream
    assert reconstructed_agent.debug_mode == agent.debug_mode
    assert reconstructed_agent.metadata == agent.metadata
