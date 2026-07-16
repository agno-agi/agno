"""get_messages(limit=N) must not return a leading orphan tool message when a system
message is present: the strip ran after the system message was prepended, leaving
[system, tool, ...] — a tool result with no preceding assistant tool_calls, which is a
hard provider API error."""

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _session():
    messages = [
        Message(role="system", content="You are helpful"),
        Message(role="user", content="Q1"),
        Message(role="assistant", content="", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "w", "arguments": "{}"}}]),
        Message(role="tool", tool_call_id="c1", content="result1"),
        Message(role="assistant", content="answer1"),
    ]
    run = RunOutput(run_id="r1", messages=messages, status=RunStatus.completed)
    run.parent_run_id = None
    return AgentSession(session_id="s1", runs=[run])


def test_limit_does_not_leave_orphan_tool_after_system():
    roles = [m.role for m in _session().get_messages(limit=3)]
    # Was ["system", "tool", "assistant"] before the fix (a leading orphan tool result).
    assert roles == ["system", "assistant"]


def test_limit_keeps_valid_tool_cycle():
    # limit=4 keeps the assistant-with-tool_calls before the tool, so the tool is valid.
    roles = [m.role for m in _session().get_messages(limit=4)]
    assert roles == ["system", "assistant", "tool", "assistant"]
