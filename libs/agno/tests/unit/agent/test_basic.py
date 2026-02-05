from unittest.mock import MagicMock, patch
from uuid import uuid4

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.utils.string import is_valid_uuid


def test_set_id():
    agent = Agent(
        id="test_id",
    )
    agent.set_id()
    assert agent.id == "test_id"


def test_set_id_from_name():
    agent = Agent(
        name="Test Name",
    )
    agent.set_id()

    # Asserting the set_id method uses the name to generate the id
    agent_id = agent.id
    expected_id = "test-name"
    assert expected_id == agent_id

    # Asserting the set_id method is deterministic
    agent.set_id()
    assert agent.id == agent_id


def test_set_id_auto_generated():
    agent = Agent()
    agent.set_id()
    assert is_valid_uuid(agent.id)


def test_deep_copy():
    """Test that Agent.deep_copy() works with all dataclass fields.

    This test ensures that all dataclass fields with defaults are properly
    handled by deep_copy(), preventing TypeError for unexpected keyword arguments.
    """
    # Create agent with minimal configuration
    # The key is that deep_copy will try to pass ALL dataclass fields to __init__
    original = Agent(name="test-agent")

    # This should not raise TypeError about unexpected keyword arguments
    copied = original.deep_copy()

    # Verify it's a different instance but with same values
    assert copied is not original
    assert copied.name == original.name
    assert copied.user_message_role == "user"
    assert copied.system_message_role == "system"

    # Test deep_copy with update
    updated = original.deep_copy(update={"name": "updated-agent"})
    assert updated.name == "updated-agent"


def test_run_preserves_metadata_when_run_is_mocked():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    with patch.object(agent, "_run", side_effect=lambda **kwargs: kwargs["run_response"]):
        run_output = agent.run("hi", metadata={"k": "v"})

    assert run_output.metadata == {"k": "v"}


def test_run_preserves_existing_run_context_metadata_when_metadata_is_not_passed():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    run_context = RunContext(run_id=str(uuid4()), session_id="test-session", metadata={"ctx": "v"})

    with patch.object(agent, "_run", side_effect=lambda **kwargs: kwargs["run_response"]):
        run_output = agent.run("hi", session_id="test-session", run_context=run_context)

    assert run_output.metadata == {"ctx": "v"}
    assert run_context.metadata == {"ctx": "v"}


def test_disconnect_connectable_tools_clears_initialized_tools():
    class ConnectableTool:
        requires_connect = True

        def __init__(self):
            self.connect_calls = 0
            self.close_calls = 0

        def connect(self):
            self.connect_calls += 1

        def close(self):
            self.close_calls += 1

    tool = ConnectableTool()
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=[tool])

    agent._connect_connectable_tools()
    assert tool.connect_calls == 1

    agent._disconnect_connectable_tools()
    assert tool.close_calls == 1
    assert agent._connectable_tools_initialized_on_run == []

    agent._connect_connectable_tools()
    assert tool.connect_calls == 2


def test_continue_run_preserves_existing_run_context_metadata_when_metadata_is_not_passed():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    run_context = RunContext(run_id=str(uuid4()), session_id="test-session", metadata={"ctx": "v"})
    run_response = RunOutput(run_id=str(uuid4()), session_id="test-session", messages=[])

    with (
        patch.object(agent, "get_tools", return_value=[]),
        patch.object(agent, "_determine_tools_for_model", return_value=[]),
        patch.object(agent, "_get_continue_run_messages", return_value=MagicMock(messages=[])),
        patch.object(agent, "_continue_run", side_effect=lambda **kwargs: kwargs["run_response"]) as continue_run_mock,
    ):
        agent.continue_run(run_response=run_response, session_id="test-session", run_context=run_context)

    called_run_context = continue_run_mock.call_args.kwargs["run_context"]
    assert called_run_context.metadata == {"ctx": "v"}
    assert run_context.metadata == {"ctx": "v"}
