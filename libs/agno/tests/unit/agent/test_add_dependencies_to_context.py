from agno.agent.agent import Agent
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session.agent import AgentSession


def test_add_dependencies_to_context_list_message_input_appends_to_last_user_message() -> None:
    dependencies = {"counter": 5, "user_id": "123"}
    agent = Agent(build_context=False)

    run_response = RunOutput(run_id="r1", session_id="s1")
    run_context = RunContext(run_id="r1", session_id="s1", dependencies=dependencies, session_state={})
    session = AgentSession(session_id="s1")

    first_user_msg = Message(role="user", content="first")
    last_user_msg = Message(role="user", content="last")
    input_messages = [
        Message(role="assistant", content="a1"),
        first_user_msg,
        Message(role="assistant", content="a2"),
        last_user_msg,
    ]

    run_messages = agent._get_run_messages(
        run_response=run_response,
        run_context=run_context,
        input=input_messages,
        session=session,
        add_history_to_context=False,
        add_dependencies_to_context=True,
    )

    assert run_messages.extra_messages is not None
    assert len(run_messages.extra_messages) == len(input_messages)

    last_user_in_run = next(m for m in reversed(run_messages.extra_messages) if m.role == "user")
    assert "<additional context>" in last_user_in_run.get_content_string()
    assert '"counter": 5' in last_user_in_run.get_content_string()
    assert "</additional context>" in last_user_in_run.get_content_string()

    # Only the last user message should get the dependencies injected.
    first_user_in_run = next(m for m in run_messages.extra_messages if m.content == "first")
    assert "<additional context>" not in first_user_in_run.get_content_string()

    # Should not mutate the original message objects passed to Agent.run/arun.
    assert last_user_msg.get_content_string() == "last"
