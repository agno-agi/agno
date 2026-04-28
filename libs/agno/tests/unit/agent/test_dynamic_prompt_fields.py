import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.session.agent import AgentSession


def test_dynamic_agent_prompt_fields_sync():
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={"tenant": "acme"},
        metadata={"user_id": "user-1"},
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        name=lambda session_state: f"{session_state['tenant']} agent",
        description=lambda run_context: f"Description for {run_context.metadata['user_id']}",
        role=lambda: "Lead assistant",
        expected_output=lambda session_state: f"Summary for {session_state['tenant']}",
        additional_context=lambda session_state: f"tenant={session_state['tenant']}",
        add_name_to_context=True,
    )

    message = agent.get_system_message(
        session=AgentSession(session_id="session-1"),
        run_context=run_context,
        user_id="user-1",
    )

    assert message is not None
    assert message.content is not None
    content = str(message.content)
    assert "Your name is: acme agent." in content
    assert "Description for user-1" in content
    assert "<your_role>\nLead assistant\n</your_role>" in content
    assert "<expected_output>\nSummary for acme\n</expected_output>" in content
    assert "tenant=acme" in content


@pytest.mark.asyncio
async def test_dynamic_agent_prompt_fields_async():
    async def name_fn(session_state):
        return f"{session_state['tenant']} agent"

    async def description_fn(run_context):
        return f"Description for {run_context.metadata['user_id']}"

    async def role_fn():
        return "Lead assistant"

    async def expected_output_fn(session_state):
        return f"Summary for {session_state['tenant']}"

    async def additional_context_fn(session_state):
        return f"tenant={session_state['tenant']}"

    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={"tenant": "acme"},
        metadata={"user_id": "user-1"},
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        name=name_fn,
        description=description_fn,
        role=role_fn,
        expected_output=expected_output_fn,
        additional_context=additional_context_fn,
        add_name_to_context=True,
    )

    message = await agent.aget_system_message(
        session=AgentSession(session_id="session-1"),
        run_context=run_context,
        user_id="user-1",
    )

    assert message is not None
    assert message.content is not None
    content = str(message.content)
    assert "Your name is: acme agent." in content
    assert "Description for user-1" in content
    assert "<your_role>\nLead assistant\n</your_role>" in content
    assert "<expected_output>\nSummary for acme\n</expected_output>" in content
    assert "tenant=acme" in content


def test_dynamic_agent_prompt_fields_validate_string_type():
    run_context = RunContext(run_id="run-1", session_id="session-1")
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        description=lambda: ["not", "a", "string"],
    )

    with pytest.raises(Exception, match="description must resolve to a string"):
        agent.get_system_message(
            session=AgentSession(session_id="session-1"),
            run_context=run_context,
        )
