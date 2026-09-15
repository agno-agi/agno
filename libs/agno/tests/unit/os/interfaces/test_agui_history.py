"""Conversation history over the AG-UI interface.

AG-UI clients send the whole transcript on every request. Agno reads history from a
session of its own, so an Agent or Team with no session to read would otherwise see only
the current turn and every earlier message would be dropped without a trace.

These tests assert the messages that actually reach the model, per turn, for an Agent and
a Team, with and without a session to read.
"""

import asyncio
from typing import Any, AsyncIterator, Iterator, List, Optional, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType, RunAgentInput
from ag_ui.core.types import (
    AssistantMessage,
    Context,
    DeveloperMessage,
    FunctionCall,
    ImageInputContent,
    InputContentUrlSource,
    ReasoningMessage,
    SystemMessage,
    TextInputContent,
    ToolCall,
    ToolMessage,
    UserMessage,
)

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.os.interfaces.agui.router import run_entity
from agno.team.team import Team
from agno.tools import Toolkit


class RecordingModel(Model):
    """Offline model that records the message list handed to it on every call."""

    def __init__(self, content: str = "ok"):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.calls: List[List[Message]] = []
        self.content = content

    @property
    def _mock_response(self) -> ModelResponse:
        return ModelResponse(content=self.content, role="assistant", response_usage=MessageMetrics())

    def _record(self, kwargs) -> None:
        self.calls.append(list(kwargs["messages"]))

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        self._record(kwargs)
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        self._record(kwargs)
        # Yield to the loop so concurrent runs actually interleave here.
        await asyncio.sleep(0)
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def _run_input(messages: List[Any], run_id: str, context: Optional[List[Context]] = None) -> RunAgentInput:
    return RunAgentInput(
        thread_id="thread-1",
        run_id=run_id,
        messages=messages,
        state=None,
        context=context or [],
        tools=[],
        forwarded_props={},
    )


async def _drive(entity, messages: List[Any], run_id: str = "run-1", user_id: Optional[str] = None, **kwargs) -> None:
    """Run one AG-UI request and insist it actually completed.

    ``run_entity`` turns any exception into a RUN_ERROR event instead of raising, so a
    test that only inspects the model would pass while every run died.
    """
    events = [event async for event in run_entity(entity, _run_input(messages, run_id, **kwargs), user_id=user_id)]

    errors = [event for event in events if event.type == EventType.RUN_ERROR]
    assert not errors, f"run failed: {[event.message for event in errors]}"
    assert events[-1].type == EventType.RUN_FINISHED


def _conversation(model: RecordingModel, call_index: int) -> List[Tuple[str, Optional[str]]]:
    """Non-system messages the model saw on a given call, as (role, content)."""
    return [(msg.role, msg.content) for msg in model.calls[call_index] if msg.role != "system"]


def _turn_1() -> List[Any]:
    return [UserMessage(id="m1", role="user", content="my name is Ada")]


def _turn_2() -> List[Any]:
    return _turn_1() + [
        AssistantMessage(id="m2", role="assistant", content="Hello Ada"),
        UserMessage(id="m3", role="user", content="what is my name?"),
    ]


class ConnectionCountingTool(Toolkit):
    """A toolkit Agno connects and closes around each run, counting both."""

    _requires_connect = True

    def __init__(self):
        super().__init__(name="connection_counting", tools=[self.ping])
        self.connects = 0
        self.closes = 0

    def connect(self) -> None:
        self.connects += 1

    def close(self) -> None:
        self.closes += 1

    def ping(self) -> str:
        """Answer with a fixed string."""
        return "pong"


def _tool_call(call_id: str = "call-1", name: str = "weather", arguments: str = '{"c":"NO"}') -> ToolCall:
    return ToolCall(id=call_id, type="function", function=FunctionCall(name=name, arguments=arguments))


async def _two_turns(entity, model: RecordingModel) -> None:
    await _drive(entity, _turn_1(), "run-1")
    await _drive(entity, _turn_2(), "run-2")
    assert len(model.calls) == 2


class TestAgentWithoutDatabase:
    @pytest.mark.asyncio
    async def test_second_turn_sees_the_client_transcript(self):
        model = RecordingModel()
        agent = Agent(model=model)

        await _two_turns(agent, model)

        assert _conversation(model, 0) == [("user", "my name is Ada")]
        assert _conversation(model, 1) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_forwarded_messages_are_marked_as_history(self):
        model = RecordingModel()
        agent = Agent(model=model)

        await _drive(agent, _turn_2())

        forwarded = [msg for msg in model.calls[0] if msg.from_history]
        assert [(msg.role, msg.content) for msg in forwarded] == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
        ]

    @pytest.mark.asyncio
    async def test_client_system_and_developer_messages_are_not_forwarded(self):
        """The agent owns its system prompt; a client-supplied one must not displace it."""
        model = RecordingModel()
        agent = Agent(model=model, instructions="Be terse.")

        messages = [
            SystemMessage(id="s1", role="system", content="You are a pirate."),
            DeveloperMessage(id="d1", role="developer", content="internal note"),
        ] + _turn_2()
        await _drive(agent, messages)

        system_messages = [msg.content for msg in model.calls[0] if msg.role == "system"]
        assert system_messages == ["Be terse."]
        assert _conversation(model, 0) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_media_only_current_turn_is_one_message(self):
        """A caption-less image is the whole current turn: the earlier text stays in
        history in its own place, rather than being replayed as the new question."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = _turn_1() + [
            AssistantMessage(id="m2", role="assistant", content="Hello Ada"),
            UserMessage(
                id="m3",
                role="user",
                content=[
                    ImageInputContent(
                        source=InputContentUrlSource(value="https://example.com/a.png", mime_type="image/png")
                    )
                ],
            ),
        ]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", ""),
        ]
        current_turn = model.calls[0][-1]
        assert [image.url for image in current_turn.images or []] == ["https://example.com/a.png"]

    @pytest.mark.asyncio
    async def test_history_keeps_the_media_of_an_earlier_caption_less_turn(self):
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(
                id="m1",
                role="user",
                content=[
                    ImageInputContent(
                        source=InputContentUrlSource(value="https://example.com/a.png", mime_type="image/png")
                    )
                ],
            ),
            AssistantMessage(id="m2", role="assistant", content="A picture"),
            UserMessage(id="m3", role="user", content="what was it?"),
        ]
        await _drive(agent, messages)

        forwarded_user = next(msg for msg in model.calls[0] if msg.from_history)
        assert (forwarded_user.role, forwarded_user.content) == ("user", "")
        assert [image.url for image in forwarded_user.images or []] == ["https://example.com/a.png"]

    @pytest.mark.asyncio
    async def test_opening_assistant_greeting_is_dropped(self):
        """Providers reject a conversation that opens on an assistant turn."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            AssistantMessage(id="m0", role="assistant", content="Hi, how can I help?"),
        ] + _turn_2()
        await _drive(agent, messages)

        assert _conversation(model, 0) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_a_reused_tool_call_id_is_forwarded_once(self):
        """Two calls against one result is the orphan the pairing exists to prevent."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(id="m1", role="user", content="weather in Oslo?"),
            AssistantMessage(id="m2", role="assistant", content=None, tool_calls=[_tool_call()]),
            ToolMessage(id="m3", role="tool", content="rain", tool_call_id="call-1"),
            AssistantMessage(id="m4", role="assistant", content="checking again", tool_calls=[_tool_call()]),
            UserMessage(id="m5", role="user", content="and tomorrow?"),
        ]
        await _drive(agent, messages)

        forwarded_calls = [msg.tool_calls for msg in model.calls[0] if msg.tool_calls]
        assert forwarded_calls == [
            [{"id": "call-1", "type": "function", "function": {"name": "weather", "arguments": '{"c":"NO"}'}}]
        ]
        assert [msg.content for msg in model.calls[0] if msg.role == "tool"] == ["rain"]

    @pytest.mark.asyncio
    async def test_history_media_is_forwarded(self):
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(
                id="m1",
                role="user",
                content=[
                    TextInputContent(text="look at this"),
                    ImageInputContent(
                        source=InputContentUrlSource(value="https://example.com/a.png", mime_type="image/png")
                    ),
                ],
            ),
            AssistantMessage(id="m2", role="assistant", content="A picture"),
            UserMessage(id="m3", role="user", content="what was it?"),
        ]
        await _drive(agent, messages)

        forwarded_user = next(msg for msg in model.calls[0] if msg.from_history)
        assert (forwarded_user.role, forwarded_user.content) == ("user", "look at this")
        assert [image.url for image in forwarded_user.images or []] == ["https://example.com/a.png"]

    @pytest.mark.asyncio
    async def test_tool_exchange_round_trips(self):
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(id="m1", role="user", content="weather in Oslo?"),
            AssistantMessage(id="m2", role="assistant", content=None, tool_calls=[_tool_call()]),
            ToolMessage(id="m3", role="tool", content="rain", tool_call_id="call-1"),
            AssistantMessage(id="m4", role="assistant", content="It rains"),
            UserMessage(id="m5", role="user", content="and tomorrow?"),
        ]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [
            ("user", "weather in Oslo?"),
            ("assistant", None),
            ("tool", "rain"),
            ("assistant", "It rains"),
            ("user", "and tomorrow?"),
        ]
        forwarded_call = next(msg for msg in model.calls[0] if msg.tool_calls)
        assert forwarded_call.tool_calls == [
            {"id": "call-1", "type": "function", "function": {"name": "weather", "arguments": '{"c":"NO"}'}}
        ]
        forwarded_result = next(msg for msg in model.calls[0] if msg.role == "tool")
        # Gemini formats a tool message with no tool_name as plain text, which leaves the
        # forwarded call unanswered.
        assert (forwarded_result.tool_call_id, forwarded_result.tool_name) == ("call-1", "weather")
        assert forwarded_result.tool_call_error is False

    @pytest.mark.asyncio
    async def test_a_reasoning_message_does_not_break_up_a_tool_exchange(self):
        """Clients interleave reasoning messages. They carry nothing for the model, but
        losing the exchange around one loses what the tool actually returned."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(id="m1", role="user", content="weather in Oslo?"),
            AssistantMessage(id="m2", role="assistant", content=None, tool_calls=[_tool_call()]),
            ReasoningMessage(id="m3", role="reasoning", content="checking the forecast"),
            ToolMessage(id="m4", role="tool", content="rain", tool_call_id="call-1"),
            UserMessage(id="m5", role="user", content="and tomorrow?"),
        ]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [
            ("user", "weather in Oslo?"),
            ("assistant", None),
            ("tool", "rain"),
            ("user", "and tomorrow?"),
        ]

    @pytest.mark.asyncio
    async def test_the_first_result_for_a_call_is_the_one_forwarded(self):
        """Two results for one call is malformed; the first is the one the model saw."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(id="m1", role="user", content="weather in Oslo?"),
            AssistantMessage(id="m2", role="assistant", content=None, tool_calls=[_tool_call()]),
            ToolMessage(id="m3", role="tool", content="rain", tool_call_id="call-1"),
            ToolMessage(id="m4", role="tool", content="snow", tool_call_id="call-1"),
            UserMessage(id="m5", role="user", content="and tomorrow?"),
        ]
        await _drive(agent, messages)

        assert [msg.content for msg in model.calls[0] if msg.role == "tool"] == ["rain"]

    @pytest.mark.asyncio
    async def test_failed_tool_result_keeps_its_error(self):
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(id="m1", role="user", content="weather in Oslo?"),
            AssistantMessage(id="m2", role="assistant", content=None, tool_calls=[_tool_call()]),
            ToolMessage(id="m3", role="tool", content="partial", tool_call_id="call-1", error="upstream refused"),
            UserMessage(id="m4", role="user", content="and tomorrow?"),
        ]
        await _drive(agent, messages)

        forwarded_result = next(msg for msg in model.calls[0] if msg.role == "tool")
        assert forwarded_result.content == "partial\nupstream refused"
        assert forwarded_result.tool_call_error is True

    @pytest.mark.asyncio
    async def test_unanswered_tool_call_is_dropped(self):
        """A tool call with no result would make providers reject the whole request."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(id="m1", role="user", content="weather in Oslo?"),
            AssistantMessage(id="m2", role="assistant", content="checking", tool_calls=[_tool_call()]),
            UserMessage(id="m3", role="user", content="never mind"),
        ]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [
            ("user", "weather in Oslo?"),
            ("assistant", "checking"),
            ("user", "never mind"),
        ]
        assert all(msg.tool_calls is None for msg in model.calls[0])

    @pytest.mark.asyncio
    async def test_contentless_assistant_turn_with_an_unanswered_call_is_dropped(self):
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(id="m1", role="user", content="weather in Oslo?"),
            AssistantMessage(id="m2", role="assistant", content="", tool_calls=[_tool_call()]),
            UserMessage(id="m3", role="user", content="never mind"),
        ]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [
            ("user", "weather in Oslo?"),
            ("user", "never mind"),
        ]

    @pytest.mark.asyncio
    async def test_tool_result_without_a_preceding_call_is_dropped(self):
        """A result that arrives before its call, or twice, is rejected by providers."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(id="m1", role="user", content="weather in Oslo?"),
            ToolMessage(id="m2", role="tool", content="rain", tool_call_id="call-1"),
            AssistantMessage(id="m3", role="assistant", content=None, tool_calls=[_tool_call()]),
            ToolMessage(id="m4", role="tool", content="rain", tool_call_id="call-1"),
            AssistantMessage(id="m5", role="assistant", content="It rains"),
            UserMessage(id="m6", role="user", content="and tomorrow?"),
        ]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [
            ("user", "weather in Oslo?"),
            ("assistant", None),
            ("tool", "rain"),
            ("assistant", "It rains"),
            ("user", "and tomorrow?"),
        ]

    @pytest.mark.asyncio
    async def test_default_agent_forwards_more_than_three_turns(self):
        """num_history_runs defaults to 3. It windows a session, not the client
        transcript, and applying it here would drop conversation on every default agent."""
        model = RecordingModel()
        agent = Agent(model=model)
        assert agent.num_history_runs == 3

        await _drive(agent, _long_transcript())

        assert _conversation(model, 0) == [
            ("user", "one"),
            ("assistant", "two"),
            ("user", "three"),
            ("assistant", "four"),
            ("user", "five"),
            ("assistant", "six"),
            ("user", "seven"),
            ("assistant", "eight"),
            ("user", "nine"),
        ]

    @pytest.mark.asyncio
    async def test_history_windows_do_not_clip_the_transcript(self):
        model = RecordingModel()
        agent = Agent(model=model, num_history_messages=1)

        await _drive(agent, _long_transcript())

        assert _conversation(model, 0) == [
            ("user", "one"),
            ("assistant", "two"),
            ("user", "three"),
            ("assistant", "four"),
            ("user", "five"),
            ("assistant", "six"),
            ("user", "seven"),
            ("assistant", "eight"),
            ("user", "nine"),
        ]

    @pytest.mark.asyncio
    async def test_a_reply_after_the_current_turn_is_not_replayed(self):
        """A transcript ending on an assistant reply asks the newest user message again;
        the reply it already got is not history."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = _turn_2() + [AssistantMessage(id="m4", role="assistant", content="You are Ada")]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_repeated_requests_leave_the_shared_entity_as_it_was(self):
        """The run mutates the object it runs: it registers connectable tools, clears the
        register afterwards, and assigns the entity an id. None of that may land on, or
        leak out of, the entity every other request shares."""
        model = RecordingModel()
        tool = ConnectionCountingTool()
        agent = Agent(name="Chat", model=model, tools=[tool])

        await _drive(agent, _turn_2(), "run-1")
        await _drive(agent, _turn_2(), "run-2")
        await _drive(agent, _turn_2(), "run-3")

        # Each forwarding request connects and closes its own copy of the toolkit, so the
        # shared one is left untouched. A copy that shared the register would connect the
        # shared toolkit once and then close it on every run.
        assert (tool.connects, tool.closes) == (0, 0)

        # The control: with nothing to forward there is no copy, and the shared toolkit is
        # the one connected and closed, which is what makes the zeros above meaningful.
        await _drive(agent, _turn_1(), "run-4")
        assert (tool.connects, tool.closes) == (1, 1)
        assert agent._connectable_tools_initialized_on_run == []
        # The identity is settled on the shared entity, not invented per request.
        assert agent.id == "chat"
        assert agent.additional_input is None

    @pytest.mark.asyncio
    async def test_concurrent_requests_do_not_see_each_other_history(self):
        model = RecordingModel()
        agent = Agent(model=model)

        ada = _turn_2()
        grace = [
            UserMessage(id="g1", role="user", content="my name is Grace"),
            AssistantMessage(id="g2", role="assistant", content="Hello Grace"),
            UserMessage(id="g3", role="user", content="who am I?"),
        ]
        await asyncio.gather(_drive(agent, ada, "run-ada"), _drive(agent, grace, "run-grace"))

        conversations = sorted(_conversation(model, index) for index in (0, 1))
        assert conversations == sorted(
            [
                [("user", "my name is Ada"), ("assistant", "Hello Ada"), ("user", "what is my name?")],
                [("user", "my name is Grace"), ("assistant", "Hello Grace"), ("user", "who am I?")],
            ]
        )

    @pytest.mark.asyncio
    async def test_media_the_interface_cannot_decode_does_not_become_the_turn(self):
        """A part that decodes to nothing leaves the message empty, and an empty message
        must not take the turn from the question the user actually asked."""
        model = RecordingModel()
        agent = Agent(model=model)

        messages = _turn_1() + [
            AssistantMessage(id="m2", role="assistant", content="Hello Ada"),
            UserMessage(
                id="m3",
                role="user",
                content=[ImageInputContent(source=InputContentUrlSource(value="", mime_type="image/png"))],
            ),
        ]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [("user", "my name is Ada")]

    @pytest.mark.asyncio
    async def test_whitespace_is_not_a_question(self):
        model = RecordingModel()
        agent = Agent(model=model)

        messages = _turn_2() + [UserMessage(id="m4", role="user", content="   ")]
        await _drive(agent, messages)

        assert _conversation(model, 0)[-1] == ("user", "what is my name?")

    @pytest.mark.asyncio
    async def test_empty_text_parts_do_not_pad_the_prompt(self):
        model = RecordingModel()
        agent = Agent(model=model)

        messages = [
            UserMessage(
                id="m1",
                role="user",
                content=[TextInputContent(text=""), TextInputContent(text="what is my name?")],
            )
        ]
        await _drive(agent, messages)

        assert _conversation(model, 0) == [("user", "what is my name?")]

    @pytest.mark.asyncio
    async def test_shared_entity_is_not_mutated(self):
        model = RecordingModel()
        agent = Agent(model=model, additional_input=[{"role": "user", "content": "few-shot"}])

        await _two_turns(agent, model)

        assert agent.additional_input == [{"role": "user", "content": "few-shot"}]
        assert _conversation(model, 1) == [
            ("user", "few-shot"),
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_dependencies_still_reach_the_current_turn(self):
        """Forwarding history must not cost the AG-UI context injection."""
        model = RecordingModel()
        agent = Agent(model=model)

        await _drive(agent, _turn_2(), context=[Context(description="city", value="Oslo")])

        current_turn = model.calls[0][-1]
        assert current_turn.role == "user"
        assert current_turn.content.startswith("what is my name?")
        assert "Oslo" in current_turn.content


def _long_transcript() -> List[Any]:
    """Four completed turns plus the current one: more than any default history window."""
    words = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    return [
        UserMessage(id=f"m{index}", role="user", content=word)
        if index % 2 == 0
        else AssistantMessage(id=f"m{index}", role="assistant", content=word)
        for index, word in enumerate(words)
    ]


class TestAgentWithDatabase:
    @pytest.mark.asyncio
    async def test_history_comes_from_the_session_without_duplication(self):
        model = RecordingModel()
        agent = Agent(model=model, db=InMemoryDb(), add_history_to_context=True)

        await _two_turns(agent, model)

        assert _conversation(model, 0) == [("user", "my name is Ada")]
        assert _conversation(model, 1) == [
            ("user", "my name is Ada"),
            ("assistant", "ok"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_transcript_is_not_forwarded_when_the_agent_opts_out_of_history(self):
        """With a database the agent owns the history decision; the interface stays out of it."""
        model = RecordingModel()
        agent = Agent(model=model, db=InMemoryDb())

        await _two_turns(agent, model)

        assert _conversation(model, 1) == [("user", "what is my name?")]


class TestAgentWithACachedSession:
    """An in-process cached session is not a substitute for a database here.

    It lives and dies with the worker, so it cannot be the source of a conversation that
    may arrive at any worker. The transcript is, and the run is told not to add history of
    its own so the cache cannot arrive on top of it.
    """

    @pytest.mark.asyncio
    async def test_a_warm_cache_is_not_read_even_on_a_single_turn(self):
        """The cache outlives a request and belongs to whoever ran this thread on this
        worker first, so a request that brings no history of its own gets none."""
        model = RecordingModel()
        agent = Agent(model=model, cache_session=True, add_history_to_context=True)

        async for _ in agent.arun(
            input="a conversation this client never saw",
            session_id="thread-1",
            stream=True,
            stream_events=True,
        ):
            pass
        await _drive(agent, _turn_1())

        assert _conversation(model, 1) == [("user", "my name is Ada")]

    @pytest.mark.asyncio
    async def test_a_cached_session_is_not_replayed_on_top_of_the_transcript(self):
        model = RecordingModel()
        agent = Agent(model=model, cache_session=True, add_history_to_context=True)

        await _two_turns(agent, model)

        assert _conversation(model, 1) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_three_turns_stay_one_conversation(self):
        model = RecordingModel()
        agent = Agent(model=model, cache_session=True, add_history_to_context=True)

        turn_3 = _turn_2() + [
            AssistantMessage(id="m4", role="assistant", content="You are Ada"),
            UserMessage(id="m5", role="user", content="and my name again?"),
        ]
        await _drive(agent, _turn_1(), "run-1")
        await _drive(agent, _turn_2(), "run-2")
        await _drive(agent, turn_3, "run-3")

        assert _conversation(model, 2) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
            ("assistant", "You are Ada"),
            ("user", "and my name again?"),
        ]

    @pytest.mark.asyncio
    async def test_a_user_switch_on_one_thread_keeps_the_transcript(self):
        """The transcript belongs to the request, not to whoever ran the thread before."""
        model = RecordingModel()
        agent = Agent(model=model, cache_session=True, add_history_to_context=True)

        await _drive(agent, _turn_1(), "run-1", user_id="ada")
        await _drive(agent, _turn_2(), "run-2", user_id="grace")

        assert _conversation(model, 1) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]


class TestTeamWithoutDatabase:
    @pytest.mark.asyncio
    async def test_second_turn_sees_the_client_transcript(self):
        leader_model = RecordingModel()
        member = Agent(name="Member", model=RecordingModel())
        team = Team(model=leader_model, members=[member])

        await _two_turns(team, leader_model)

        assert _conversation(leader_model, 0) == [("user", "my name is Ada")]
        assert _conversation(leader_model, 1) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_member_identities_are_settled_once_not_per_request(self):
        """A member with no name is given a random id. Letting each request's copy mint
        its own would give one member a different id on every turn."""
        leader_model = RecordingModel()
        team = Team(model=leader_model, members=[Agent(model=RecordingModel())])

        await _drive(team, _turn_2(), "run-1")
        first = team.members[0].id
        await _drive(team, _turn_2(), "run-2")

        assert first is not None
        assert team.members[0].id == first

    @pytest.mark.asyncio
    async def test_a_members_factory_is_not_a_list_of_members(self):
        """Team members can be a callable resolved per run. Walking it as a list raised."""
        leader_model = RecordingModel()
        team = Team(model=leader_model, members=lambda: [Agent(name="Member", model=RecordingModel())])

        await _two_turns(team, leader_model)

        assert _conversation(leader_model, 1) == [
            ("user", "my name is Ada"),
            ("assistant", "Hello Ada"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_shared_team_is_not_mutated(self):
        leader_model = RecordingModel()
        team = Team(model=leader_model, members=[Agent(name="Member", model=RecordingModel())])

        await _two_turns(team, leader_model)

        assert team.additional_input is None


class TestTeamWithDatabase:
    @pytest.mark.asyncio
    async def test_history_comes_from_the_session_without_duplication(self):
        leader_model = RecordingModel()
        team = Team(
            model=leader_model,
            members=[Agent(name="Member", model=RecordingModel())],
            db=InMemoryDb(),
            add_history_to_context=True,
        )

        await _two_turns(team, leader_model)

        assert _conversation(leader_model, 0) == [("user", "my name is Ada")]
        assert _conversation(leader_model, 1) == [
            ("user", "my name is Ada"),
            ("assistant", "ok"),
            ("user", "what is my name?"),
        ]

    @pytest.mark.asyncio
    async def test_transcript_is_not_forwarded_when_the_team_opts_out_of_history(self):
        leader_model = RecordingModel()
        team = Team(model=leader_model, members=[Agent(name="Member", model=RecordingModel())], db=InMemoryDb())

        await _two_turns(team, leader_model)

        assert _conversation(leader_model, 1) == [("user", "what is my name?")]
