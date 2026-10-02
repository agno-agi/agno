from functools import partial

import pytest

from agno.agent import Agent
from agno.agent import _messages as agent_messages
from agno.agent._messages import format_message_with_state_variables
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.team import Team
from agno.team import _messages as team_messages
from agno.team._messages import _format_message_with_state_variables


@pytest.fixture(params=["agent", "team"])
def formatter(request):
    if request.param == "agent":
        return partial(format_message_with_state_variables, Agent())

    return partial(
        _format_message_with_state_variables,
        Team(members=[]),
    )


@pytest.mark.parametrize(
    "message,context,expected",
    [
        (
            "Wrap equations in $$...$$.",
            {},
            "Wrap equations in $$...$$.",
        ),
        (
            "Is $5 cheap? and $x",
            {"dependencies": {"x": "1"}},
            "Is $5 cheap? and $x",
        ),
        (
            "Hi {first-name}",
            {"session_state": {"first-name": "Bo"}},
            "Hi Bo",
        ),
        (
            "Hi {name}; $x; $$...$$; ${x}; $${x}; {missing}",
            {"session_state": {"name": "Bo"}, "dependencies": {"x": "1"}},
            "Hi Bo; $x; $$...$$; ${x}; $${x}; {missing}",
        ),
        (
            "{first-name} {user.name} {user_name} {123}",
            {"session_state": {"first-name": "Bo", "user.name": "Alice", "user_name": "Bob", "123": "number"}},
            "Bo Alice Bob number",
        ),
        (
            "{a} {b}",
            {"dependencies": {"a": r"{b} $b $$ ${b} \1 \g<1>", "b": "resolved"}},
            r"{b} $b $$ ${b} \1 \g<1> resolved",
        ),
        (
            "{b} {a}",
            {"dependencies": {"a": "resolved", "b": "{a}"}},
            "{a} resolved",
        ),
        (
            "{count} {enabled} {nothing} {empty}",
            {"session_state": {"count": 0, "enabled": False, "nothing": None, "empty": ""}},
            "0 False None ",
        ),
        (
            '{{name}} {name} {name} {missing} {"key": "value"}',
            {"session_state": {"name": "Bo"}},
            '{Bo} Bo Bo {missing} {"key": "value"}',
        ),
        (
            "{from_state} {from_dependencies} {from_metadata} {user_id}",
            {
                "session_state": {"from_state": "state"},
                "dependencies": {"from_state": "dependency", "from_dependencies": "dependency"},
                "metadata": {
                    "from_state": "metadata",
                    "from_dependencies": "metadata",
                    "from_metadata": "metadata",
                },
                "user_id": "user",
            },
            "state dependency metadata user",
        ),
        (
            "{user_id}",
            {"metadata": {"user_id": "metadata-user"}, "user_id": "fallback-user"},
            "metadata-user",
        ),
    ],
)
def test_state_variable_formatting(formatter, message, context, expected):
    run_context = RunContext(
        run_id="test-run",
        session_id="test-session",
        **context,
    )

    assert formatter(message, run_context=run_context) == expected


@pytest.mark.parametrize("message", [None, 42, ["{name}", "$$"], {"text": "{name}"}])
def test_non_string_message_is_unchanged(formatter, message):
    run_context = RunContext(run_id="test-run", session_id="test-session", session_state={"name": "Bo"})

    assert formatter(message, run_context=run_context) is message


@pytest.mark.parametrize("message", ["plain text", "$$...$$", "{unknown} $x ${x} $$"])
def test_message_without_context_is_unchanged(formatter, message):
    assert formatter(message) == message


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("resolve_in_context", [False, True], ids=["disabled", "enabled"])
async def test_system_and_user_messages(formatter, async_mode, resolve_in_context):
    subject = formatter.args[0]
    message = "Hi {first-name}; $$...$$; $x; {x}"
    subject.system_message = message
    subject.resolve_in_context = resolve_in_context
    run_context = RunContext(
        run_id="test-run",
        session_id="test-session",
        session_state={"first-name": "Bo"},
        dependencies={"x": "1"},
    )

    if isinstance(subject, Agent):
        session = AgentSession(session_id="test-session")
        system_builder = agent_messages.aget_system_message if async_mode else agent_messages.get_system_message
        user_builder = agent_messages.aget_user_message if async_mode else agent_messages.get_user_message
        user_kwargs = {"input": message, "run_response": RunOutput()}
    else:
        session = TeamSession(session_id="test-session")
        system_builder = team_messages.aget_system_message if async_mode else team_messages.get_system_message
        user_builder = team_messages._aget_user_message if async_mode else team_messages._get_user_message
        user_kwargs = {"input_message": message, "run_response": TeamRunOutput()}

    system_message = system_builder(subject, session=session, run_context=run_context)
    user_message = user_builder(subject, run_context=run_context, **user_kwargs)
    if async_mode:
        system_message = await system_message
        user_message = await user_message

    expected = "Hi Bo; $$...$$; $x; 1" if resolve_in_context else message
    assert system_message is not None
    assert user_message is not None
    assert system_message.content == expected
    assert user_message.content == expected
