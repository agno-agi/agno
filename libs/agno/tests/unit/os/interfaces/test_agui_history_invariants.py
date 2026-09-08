"""Invariants the AG-UI history extraction holds for every transcript shape.

The per-shape tests beside this file assert what a particular conversation should produce.
These assert the properties that have to hold whatever the client sends, over a catalogue
of shapes: history and the current turn partition the transcript, order survives, nothing
is forwarded twice, and every forwarded tool call is answered exactly once.

Each fixture gives its messages distinct keys, asserted below, so a forwarded message can
be traced back to exactly one source message.
"""

from typing import Any, List, Optional, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

import base64

from ag_ui.core.types import (
    ActivityMessage,
    AssistantMessage,
    BinaryInputContent,
    DeveloperMessage,
    FunctionCall,
    ImageInputContent,
    InputContentDataSource,
    InputContentUrlSource,
    ReasoningMessage,
    SystemMessage,
    TextInputContent,
    ToolCall,
    ToolMessage,
    UserMessage,
)

from agno.agent.agent import Agent
from agno.models.message import Message
from agno.os.interfaces.agui.input import extract_media, extract_message_history, extract_user_input
from agno.team.team import Team


def _tool_call(call_id: str, name: str = "weather", arguments: str = "{}") -> ToolCall:
    return ToolCall(id=call_id, type="function", function=FunctionCall(name=name, arguments=arguments))


def _shapes() -> List[Tuple[str, List[Any]]]:
    """Transcript shapes a client can send, named for the failure each one guards."""
    return [
        ("single turn", [UserMessage(id="a1", role="user", content="q1")]),
        (
            "two turns",
            [
                UserMessage(id="b1", role="user", content="q1"),
                AssistantMessage(id="b2", role="assistant", content="r1"),
                UserMessage(id="b3", role="user", content="q2"),
            ],
        ),
        (
            "ends on an assistant reply",
            [
                UserMessage(id="c1", role="user", content="q1"),
                AssistantMessage(id="c2", role="assistant", content="r1"),
                UserMessage(id="c3", role="user", content="q2"),
                AssistantMessage(id="c4", role="assistant", content="r2"),
            ],
        ),
        (
            "opens on an assistant greeting",
            [
                AssistantMessage(id="d0", role="assistant", content="greeting"),
                UserMessage(id="d1", role="user", content="q1"),
                AssistantMessage(id="d2", role="assistant", content="r1"),
                UserMessage(id="d3", role="user", content="q2"),
            ],
        ),
        (
            "system and developer prefix",
            [
                SystemMessage(id="e0", role="system", content="be a pirate"),
                DeveloperMessage(id="e0b", role="developer", content="note"),
                UserMessage(id="e1", role="user", content="q1"),
                AssistantMessage(id="e2", role="assistant", content="r1"),
                UserMessage(id="e3", role="user", content="q2"),
            ],
        ),
        (
            "current turn carries media only",
            [
                UserMessage(id="f1", role="user", content="q1"),
                AssistantMessage(id="f2", role="assistant", content="r1"),
                UserMessage(
                    id="f3",
                    role="user",
                    content=[
                        ImageInputContent(
                            source=InputContentUrlSource(value="https://example.com/f.png", mime_type="image/png")
                        )
                    ],
                ),
            ],
        ),
        (
            "earlier turn carries media and a caption",
            [
                UserMessage(
                    id="g1",
                    role="user",
                    content=[
                        TextInputContent(text="q1"),
                        ImageInputContent(
                            source=InputContentUrlSource(value="https://example.com/g.png", mime_type="image/png")
                        ),
                    ],
                ),
                AssistantMessage(id="g2", role="assistant", content="r1"),
                UserMessage(id="g3", role="user", content="q2"),
            ],
        ),
        (
            "complete tool exchange",
            [
                UserMessage(id="h1", role="user", content="q1"),
                AssistantMessage(id="h2", role="assistant", content=None, tool_calls=[_tool_call("h-call")]),
                ToolMessage(id="h3", role="tool", content="result", tool_call_id="h-call"),
                AssistantMessage(id="h4", role="assistant", content="r1"),
                UserMessage(id="h5", role="user", content="q2"),
            ],
        ),
        (
            "unanswered tool call",
            [
                UserMessage(id="i1", role="user", content="q1"),
                AssistantMessage(id="i2", role="assistant", content="r1", tool_calls=[_tool_call("i-call")]),
                UserMessage(id="i3", role="user", content="q2"),
            ],
        ),
        (
            "tool result before its call",
            [
                UserMessage(id="j1", role="user", content="q1"),
                ToolMessage(id="j2", role="tool", content="early", tool_call_id="j-call"),
                AssistantMessage(id="j3", role="assistant", content=None, tool_calls=[_tool_call("j-call")]),
                ToolMessage(id="j4", role="tool", content="result", tool_call_id="j-call"),
                UserMessage(id="j5", role="user", content="q2"),
            ],
        ),
        (
            "call id reused across two assistant messages",
            [
                UserMessage(id="k1", role="user", content="q1"),
                AssistantMessage(id="k2", role="assistant", content=None, tool_calls=[_tool_call("k-call")]),
                ToolMessage(id="k3", role="tool", content="result", tool_call_id="k-call"),
                AssistantMessage(id="k4", role="assistant", content="r1", tool_calls=[_tool_call("k-call")]),
                UserMessage(id="k5", role="user", content="q2"),
            ],
        ),
        (
            "call id repeated inside one assistant message",
            [
                UserMessage(id="l1", role="user", content="q1"),
                AssistantMessage(
                    id="l2",
                    role="assistant",
                    content=None,
                    tool_calls=[_tool_call("l-call"), _tool_call("l-call")],
                ),
                ToolMessage(id="l3", role="tool", content="result", tool_call_id="l-call"),
                UserMessage(id="l4", role="user", content="q2"),
            ],
        ),
        (
            "empty and activity messages",
            [
                UserMessage(id="m1", role="user", content=""),
                ActivityMessage(id="m2", role="activity", activity_type="progress", content={"step": 1}),
                AssistantMessage(id="m3", role="assistant", content=""),
                UserMessage(id="m4", role="user", content="q1"),
                AssistantMessage(id="m5", role="assistant", content="r1"),
                UserMessage(id="m6", role="user", content="q2"),
            ],
        ),
        ("no user message at all", [AssistantMessage(id="n1", role="assistant", content="r1")]),
        ("empty transcript", []),
        (
            "newest user message is empty",
            [
                UserMessage(id="o1", role="user", content="q1"),
                AssistantMessage(id="o2", role="assistant", content="r1"),
                UserMessage(id="o3", role="user", content="q2"),
                UserMessage(id="o4", role="user", content=""),
            ],
        ),
        (
            "tool result carries nothing",
            [
                UserMessage(id="p1", role="user", content="q1"),
                AssistantMessage(id="p2", role="assistant", content=None, tool_calls=[_tool_call("p-call")]),
                ToolMessage(id="p3", role="tool", content="", tool_call_id="p-call"),
                UserMessage(id="p4", role="user", content="q2"),
            ],
        ),
        (
            "two calls then two results",
            [
                UserMessage(id="q1", role="user", content="q1"),
                AssistantMessage(id="q2", role="assistant", content="calling a", tool_calls=[_tool_call("q-a")]),
                AssistantMessage(id="q3", role="assistant", content="calling b", tool_calls=[_tool_call("q-b")]),
                ToolMessage(id="q4", role="tool", content="ra", tool_call_id="q-a"),
                ToolMessage(id="q5", role="tool", content="rb", tool_call_id="q-b"),
                UserMessage(id="q6", role="user", content="q2"),
            ],
        ),
        (
            "dropped opening turn reuses a call id",
            [
                AssistantMessage(
                    id="r1", role="assistant", content="calling alpha", tool_calls=[_tool_call("r-call", "alpha")]
                ),
                ToolMessage(id="r2", role="tool", content="ra", tool_call_id="r-call"),
                UserMessage(id="r3", role="user", content="q1"),
                AssistantMessage(
                    id="r4", role="assistant", content="calling beta", tool_calls=[_tool_call("r-call", "beta")]
                ),
                ToolMessage(id="r5", role="tool", content="rb", tool_call_id="r-call"),
                UserMessage(id="r6", role="user", content="q2"),
            ],
        ),
        (
            "call id answered twice in two blocks",
            [
                UserMessage(id="u1", role="user", content="q1"),
                AssistantMessage(id="u2", role="assistant", content="calling once", tool_calls=[_tool_call("u-call")]),
                ToolMessage(id="u3", role="tool", content="ra", tool_call_id="u-call"),
                AssistantMessage(id="u4", role="assistant", content="calling twice", tool_calls=[_tool_call("u-call")]),
                ToolMessage(id="u5", role="tool", content="rb", tool_call_id="u-call"),
                UserMessage(id="u6", role="user", content="q2"),
            ],
        ),
        (
            "two results for one call id, adjacent",
            [
                UserMessage(id="v1", role="user", content="q1"),
                AssistantMessage(id="v2", role="assistant", content=None, tool_calls=[_tool_call("v-call")]),
                ToolMessage(id="v3", role="tool", content="first", tool_call_id="v-call"),
                ToolMessage(id="v4", role="tool", content="second", tool_call_id="v-call"),
                UserMessage(id="v5", role="user", content="q2"),
            ],
        ),
        (
            "inline media the interface has to decode",
            [
                UserMessage(
                    id="w1",
                    role="user",
                    content=[
                        TextInputContent(text="q1"),
                        ImageInputContent(
                            source=InputContentDataSource(
                                value=base64.b64encode(b"inline-image-bytes").decode(), mime_type="image/png"
                            )
                        ),
                    ],
                ),
                AssistantMessage(id="w2", role="assistant", content="r1"),
                UserMessage(
                    id="w3",
                    role="user",
                    content=[BinaryInputContent(mime_type="image/jpeg", data=base64.b64encode(b"binary").decode())],
                ),
                UserMessage(id="w4", role="user", content="q2"),
            ],
        ),
        (
            "reasoning message inside a tool block",
            [
                UserMessage(id="x1", role="user", content="q1"),
                AssistantMessage(id="x2", role="assistant", content=None, tool_calls=[_tool_call("x-call")]),
                ReasoningMessage(id="x3", role="reasoning", content="thinking"),
                ToolMessage(id="x4", role="tool", content="rx", tool_call_id="x-call"),
                UserMessage(id="x5", role="user", content="q2"),
            ],
        ),
        (
            "newest user message carries only a deprecated binary part",
            [
                UserMessage(id="y1", role="user", content="q1"),
                AssistantMessage(id="y2", role="assistant", content="r1"),
                UserMessage(
                    id="y3",
                    role="user",
                    content=[BinaryInputContent(mime_type="image/png", data=base64.b64encode(b"newest").decode())],
                ),
            ],
        ),
        (
            "reasoning message between turns",
            [
                UserMessage(id="s1", role="user", content="q1"),
                ReasoningMessage(id="s2", role="reasoning", content="thinking"),
                AssistantMessage(id="s3", role="assistant", content="r1"),
                UserMessage(id="s4", role="user", content="q2"),
            ],
        ),
        (
            "trailing tool results with no call",
            [
                UserMessage(id="t1", role="user", content="q1"),
                UserMessage(id="t2", role="user", content="q2"),
                ToolMessage(id="t3", role="tool", content="orphan", tool_call_id="t-call"),
            ],
        ),
    ]


SHAPES = _shapes()
SHAPE_IDS = [name for name, _ in SHAPES]


def _turn_index(messages: List[Any]) -> Optional[int]:
    """The turn the request asks about, derived from the protocol rather than the code
    under test: the newest user message that carries text or media."""
    fallback = None
    for index in range(len(messages) - 1, -1, -1):
        msg = messages[index]
        if msg.role != "user":
            continue
        if _text_of(msg) or _media_parts(msg):
            return index
        if fallback is None:
            fallback = index
    return fallback


def _text_of(msg: Any) -> str:
    if isinstance(msg.content, str):
        return msg.content
    if isinstance(msg.content, list):
        return "\n".join(part.text for part in msg.content if getattr(part, "type", None) == "text")
    return ""


def _media_parts(msg: Any) -> List[Any]:
    if not isinstance(msg.content, list):
        return []
    media_types = ("binary", "image", "audio", "video", "document")
    return [part for part in msg.content if getattr(part, "type", None) in media_types]


def _source_keys(messages: List[Any]) -> List[Optional[Tuple[str, str]]]:
    return [_source_key(msg) for msg in messages]


def _source_key(msg: Any) -> Optional[Tuple[str, ...]]:
    """How a client message would look once forwarded, or None if it never can be."""
    if msg.role == "user":
        return ("user", _text_of(msg))
    if msg.role == "assistant":
        return ("assistant", msg.content or "")
    if msg.role == "tool":
        # The content of a result distinguishes two results for one call id. The join with
        # an error is the interface's rule, pinned on its own by the failed-tool test.
        return ("tool", msg.tool_call_id, "\n".join(part for part in (msg.content, msg.error) if part))
    return None


def _forwarded_key(msg: Message) -> Tuple[str, ...]:
    if msg.role == "tool":
        return ("tool", msg.tool_call_id or "", msg.content or "")
    return (msg.role, msg.content or "")


@pytest.mark.parametrize("messages", [messages for _, messages in SHAPES], ids=SHAPE_IDS)
class TestHistoryInvariants:
    def test_history_is_the_transcript_before_the_current_turn_in_order(self, messages):
        """Every forwarded message traces back to one distinct client message that
        precedes the current turn, and the order they arrived in survives."""
        history = extract_message_history(messages)
        source_keys = _source_keys(messages)
        turn = _turn_index(messages)
        boundary = len(messages) if turn is None else turn

        matched: List[int] = []
        cursor = 0
        for forwarded in history:
            key = _forwarded_key(forwarded)
            while cursor < len(source_keys) and source_keys[cursor] != key:
                cursor += 1
            assert cursor < len(source_keys), (
                f"forwarded {key} matches no remaining client message, so history reorders, "
                f"repeats or invents a message"
            )
            matched.append(cursor)
            cursor += 1

        assert all(index < boundary for index in matched), (
            f"history reaches the current turn or past it: matched {matched}, boundary {boundary}"
        )

    def test_every_earlier_user_message_that_said_something_is_forwarded(self, messages):
        """The complement of the ordering invariant: history drops nothing it should keep."""
        turn = _turn_index(messages)
        boundary = len(messages) if turn is None else turn
        expected = [
            _source_key(msg)
            for index, msg in enumerate(messages[:boundary])
            if msg.role == "user" and (_text_of(msg) or _media_parts(msg))
        ]
        # An opening user message can only be dropped with the whole opening block, which
        # cannot happen: a user message opens history legally.
        forwarded = [_forwarded_key(msg) for msg in extract_message_history(messages) if msg.role == "user"]
        assert forwarded == expected

    def test_history_opens_on_a_user_message(self, messages):
        """Providers reject a conversation whose first message is not from the user."""
        history = extract_message_history(messages)
        if history:
            assert history[0].role == "user"

    def test_every_forwarded_call_is_answered_in_its_own_block(self, messages):
        """Providers accept a call and its result adjacent, and reject either half alone."""
        history = extract_message_history(messages)

        pending: List[str] = []
        for msg in history:
            if msg.role == "tool":
                assert pending, "a result was forwarded outside any call block"
                assert msg.tool_call_id == pending.pop(0), "a result was forwarded out of its call's order"
                continue
            assert not pending, f"a call block was interrupted before its results: {pending}"
            pending = [tool_call["id"] for tool_call in msg.tool_calls or []]

        assert not pending, f"a forwarded call was left unanswered: {pending}"

    def test_no_call_id_is_forwarded_twice(self, messages):
        history = extract_message_history(messages)
        called = [tool_call["id"] for msg in history for tool_call in msg.tool_calls or []]
        assert len(called) == len(set(called))

    def test_a_forwarded_result_names_the_tool_its_own_call_named(self, messages):
        history = extract_message_history(messages)
        names = {}
        for msg in history:
            for tool_call in msg.tool_calls or []:
                names[tool_call["id"]] = tool_call["function"]["name"]
            if msg.role == "tool":
                assert msg.tool_name == names.get(msg.tool_call_id)

    def test_forwarded_messages_carry_something_for_the_model(self, messages):
        for msg in extract_message_history(messages):
            assert msg.content or msg.tool_calls or msg.images or msg.audio or msg.videos or msg.files

    def test_the_current_turn_is_the_newest_user_message_that_said_something(self, messages):
        turn = _turn_index(messages)
        assert extract_user_input(messages) == ("" if turn is None else _text_of(messages[turn]))

        images, audio, videos, files = extract_media(messages)
        expected_media = [] if turn is None else _media_parts(messages[turn])
        assert len(images) + len(audio) + len(videos) + len(files) == len(expected_media)


def test_a_stateless_resume_request_tells_the_client_what_is_missing():
    """The cookbook quotes this text; a client sees it as the stream's RUN_ERROR."""
    import asyncio

    from ag_ui.core import EventType, RunAgentInput

    from agno.os.interfaces.agui.router import run_entity

    agent = Agent(name="Stateless", model=None)
    run_input = RunAgentInput(
        thread_id="thread-1",
        run_id="run-1",
        messages=[
            UserMessage(id="u1", role="user", content="q1"),
            AssistantMessage(id="a1", role="assistant", content=None, tool_calls=[_tool_call("call-1")]),
            ToolMessage(id="t1", role="tool", content="done", tool_call_id="call-1"),
        ],
        state=None,
        context=[],
        tools=[],
        forwarded_props={},
    )

    async def collect():
        return [event async for event in run_entity(agent, run_input)]

    events = asyncio.run(collect())
    errors = [event for event in events if event.type == EventType.RUN_ERROR]
    assert [event.message for event in errors] == ["Frontend tool resume requires a database"]


def test_a_remote_resume_request_tells_the_client_what_is_missing():
    """The cookbook quotes this text too, for the entity kind that can never resume here."""
    import asyncio
    from unittest.mock import MagicMock

    from ag_ui.core import EventType, RunAgentInput

    from agno.agent.remote import RemoteAgent
    from agno.os.interfaces.agui.router import run_entity

    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="remote-agent")
    remote_agent.agentos_client = MagicMock()
    run_input = RunAgentInput(
        thread_id="thread-1",
        run_id="run-1",
        messages=[
            UserMessage(id="u1", role="user", content="q1"),
            AssistantMessage(id="a1", role="assistant", content=None, tool_calls=[_tool_call("call-1")]),
            ToolMessage(id="t1", role="tool", content="done", tool_call_id="call-1"),
        ],
        state=None,
        context=[],
        tools=[],
        forwarded_props={},
    )

    async def collect():
        return [event async for event in run_entity(remote_agent, run_input)]

    events = asyncio.run(collect())
    errors = [event for event in events if event.type == EventType.RUN_ERROR]
    assert [event.message for event in errors] == ["Frontend tool resume requires a local Agent or Team"]


def test_every_shape_keys_its_messages_distinctly():
    """The tracing above is only exact while no two messages in a shape look alike."""
    for name, messages in SHAPES:
        keys = [key for key in _source_keys(messages) if key is not None]
        assert len(keys) == len(set(keys)), f"shape {name!r} repeats a message key: {keys}"


def test_the_history_window_default_the_documentation_rests_on():
    """The forwarding path documents why it ignores this; that rests on the default being set."""
    assert Agent().num_history_runs == 3
    assert Team(members=[Agent(name="Member")]).num_history_runs == 3
