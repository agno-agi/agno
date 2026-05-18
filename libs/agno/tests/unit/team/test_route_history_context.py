from typing import Any, AsyncIterator, Iterator, Optional

import pytest

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.base import RunContext, RunStatus
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._messages import _aget_run_messages, _get_run_messages
from agno.team.team import Team, TeamMode
from agno.utils.agent import scrub_tool_results_from_run_output


class MockModel(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")

    def get_instructions_for_model(self, *args: Any, **kwargs: Any) -> Optional[list[str]]:
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any) -> Optional[Message]:
        return None

    async def aget_instructions_for_model(self, *args: Any, **kwargs: Any) -> Optional[list[str]]:
        return None

    async def aget_system_message_for_model(self, *args: Any, **kwargs: Any) -> Optional[Message]:
        return None

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise NotImplementedError

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError


def _delegated_route_run(*, content: str = "math_agent answered: 4", final_assistant: Optional[str] = None):
    messages = [
        Message(role="user", content="Q1: what is 2+2?"),
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "delegate_task_to_member",
                        "arguments": '{"member_id": "math_agent", "task": "Q1: what is 2+2?"}',
                    },
                }
            ],
        ),
        Message(role="tool", content=content, tool_call_id="call-1"),
    ]
    if final_assistant is not None:
        messages.append(Message(role="assistant", content=final_assistant))

    return TeamRunOutput(
        run_id="run-1",
        team_id="brain-team",
        status=RunStatus.completed,
        content=content,
        messages=messages,
    )


def _team(**kwargs: Any) -> Team:
    return Team(
        id="brain-team",
        name="brain-team",
        model=MockModel(),
        members=[],
        mode=TeamMode.route,
        add_history_to_context=True,
        num_history_runs=2,
        **kwargs,
    )


def _session(previous_run: TeamRunOutput) -> TeamSession:
    return TeamSession(session_id="session-1", team_id="brain-team", runs=[previous_run])


def _history_messages(messages: list[Message]) -> list[Message]:
    return [message for message in messages if message.from_history]


def test_route_history_keeps_completed_turn_when_tool_messages_are_not_stored():
    previous_run = _delegated_route_run(content="math_agent answered: 4")
    scrub_tool_results_from_run_output(previous_run)

    run_messages = _get_run_messages(
        _team(store_tool_messages=False),
        run_response=TeamRunOutput(run_id="run-2", team_id="brain-team", status=RunStatus.running),
        run_context=RunContext(run_id="run-2", session_id="session-1"),
        session=_session(previous_run),
        input_message="Q2: what is Newton's second law?",
        add_history_to_context=True,
    )

    history = _history_messages(run_messages.messages)
    assert [(message.role, message.content) for message in history] == [
        ("user", "Q1: what is 2+2?"),
        ("assistant", "math_agent answered: 4"),
    ]
    assert all(message.role != "tool" for message in history)
    assert all(not message.tool_calls for message in history)


def test_route_history_keeps_completed_turn_when_tool_calls_are_filtered_out():
    previous_run = _delegated_route_run(content="math_agent answered: 4")

    run_messages = _get_run_messages(
        _team(max_tool_calls_from_history=0),
        run_response=TeamRunOutput(run_id="run-2", team_id="brain-team", status=RunStatus.running),
        run_context=RunContext(run_id="run-2", session_id="session-1"),
        session=_session(previous_run),
        input_message="Q2: what is Newton's second law?",
        add_history_to_context=True,
    )

    history = _history_messages(run_messages.messages)
    assert [(message.role, message.content) for message in history] == [
        ("user", "Q1: what is 2+2?"),
        ("assistant", "math_agent answered: 4"),
    ]
    assert all(message.role != "tool" for message in history)
    assert all(not message.tool_calls for message in history)


def test_route_history_does_not_duplicate_existing_assistant_answer():
    previous_run = _delegated_route_run(content="The answer is 4.", final_assistant="The answer is 4.")
    scrub_tool_results_from_run_output(previous_run)

    run_messages = _get_run_messages(
        _team(store_tool_messages=False),
        run_response=TeamRunOutput(run_id="run-2", team_id="brain-team", status=RunStatus.running),
        run_context=RunContext(run_id="run-2", session_id="session-1"),
        session=_session(previous_run),
        input_message="Q2: what is Newton's second law?",
        add_history_to_context=True,
    )

    history = _history_messages(run_messages.messages)
    assert [(message.role, message.content) for message in history] == [
        ("user", "Q1: what is 2+2?"),
        ("assistant", "The answer is 4."),
    ]


def test_route_history_does_not_override_existing_visible_assistant_answer():
    previous_run = TeamRunOutput(
        run_id="run-1",
        team_id="brain-team",
        status=RunStatus.completed,
        content="different serialized run output",
        messages=[
            Message(role="user", content="Q1: what is 2+2?"),
            Message(role="assistant", content="The answer is 4."),
        ],
    )

    run_messages = _get_run_messages(
        _team(store_tool_messages=False),
        run_response=TeamRunOutput(run_id="run-2", team_id="brain-team", status=RunStatus.running),
        run_context=RunContext(run_id="run-2", session_id="session-1"),
        session=_session(previous_run),
        input_message="Q2: what is Newton's second law?",
        add_history_to_context=True,
    )

    history = _history_messages(run_messages.messages)
    assert [(message.role, message.content) for message in history] == [
        ("user", "Q1: what is 2+2?"),
        ("assistant", "The answer is 4."),
    ]


def test_route_history_does_not_synthesize_content_for_unfinished_runs():
    previous_run = TeamRunOutput(
        run_id="run-1",
        team_id="brain-team",
        status=RunStatus.running,
        content="partial delegated answer",
        messages=[Message(role="user", content="Q1: what is 2+2?")],
    )

    run_messages = _get_run_messages(
        _team(store_tool_messages=False),
        run_response=TeamRunOutput(run_id="run-2", team_id="brain-team", status=RunStatus.running),
        run_context=RunContext(run_id="run-2", session_id="session-1"),
        session=_session(previous_run),
        input_message="Q2: what is Newton's second law?",
        add_history_to_context=True,
    )

    history = _history_messages(run_messages.messages)
    assert [(message.role, message.content) for message in history] == [("user", "Q1: what is 2+2?")]


def test_route_history_does_not_synthesize_empty_run_content():
    previous_run = TeamRunOutput(
        run_id="run-1",
        team_id="brain-team",
        status=RunStatus.completed,
        content=[],
        messages=[Message(role="user", content="Q1: what is 2+2?")],
    )

    run_messages = _get_run_messages(
        _team(store_tool_messages=False),
        run_response=TeamRunOutput(run_id="run-2", team_id="brain-team", status=RunStatus.running),
        run_context=RunContext(run_id="run-2", session_id="session-1"),
        session=_session(previous_run),
        input_message="Q2: what is Newton's second law?",
        add_history_to_context=True,
    )

    history = _history_messages(run_messages.messages)
    assert [(message.role, message.content) for message in history] == [("user", "Q1: what is 2+2?")]


@pytest.mark.asyncio
async def test_async_route_history_matches_sync_behavior_when_tool_messages_are_not_stored():
    previous_run = _delegated_route_run(content="math_agent answered: 4")
    scrub_tool_results_from_run_output(previous_run)

    run_messages = await _aget_run_messages(
        _team(store_tool_messages=False),
        run_response=TeamRunOutput(run_id="run-2", team_id="brain-team", status=RunStatus.running),
        run_context=RunContext(run_id="run-2", session_id="session-1"),
        session=_session(previous_run),
        input_message="Q2: what is Newton's second law?",
        add_history_to_context=True,
    )

    history = _history_messages(run_messages.messages)
    assert [(message.role, message.content) for message in history] == [
        ("user", "Q1: what is 2+2?"),
        ("assistant", "math_agent answered: 4"),
    ]
