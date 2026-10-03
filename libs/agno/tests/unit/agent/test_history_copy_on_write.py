"""History messages are copied before being tagged with from_history.

Messages without media take a shallow (model_copy) copy for speed, so the
session's cached Message objects must never be mutated by a later run's
history tagging. Media-carrying messages keep a deep copy because the
media-offload refresh writes into the media objects in place.
"""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse


class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="ok",
            role="assistant",
            response_usage=MessageMetrics(),
        )

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
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def _make_agent() -> Agent:
    # cache_session=True keeps the session's Message objects live on the
    # agent, so any in-place mutation of history by a later run would be
    # visible on the earlier run's messages.
    return Agent(
        model=MockModel(),
        db=InMemoryDb(),
        add_history_to_context=True,
        cache_session=True,
        telemetry=False,
    )


def test_history_tagging_does_not_mutate_cached_messages():
    agent = _make_agent()
    first = agent.run("first turn", session_id="s1")
    assert all(m.from_history is False for m in first.messages)

    second = agent.run("second turn", session_id="s1")

    # The originals from run 1 (aliased into the cached session) are untouched
    assert all(m.from_history is False for m in first.messages)

    # Run 2's context contains tagged copies of run 1's messages, not the originals
    history = [m for m in second.messages if m.from_history]
    assert len(history) >= 2
    first_ids = {id(m) for m in first.messages}
    assert all(id(m) not in first_ids for m in history)
    assert any("first turn" in str(m.content) for m in history)


def test_media_history_messages_are_deep_copied():
    agent = _make_agent()
    first = agent.run(
        "describe this",
        images=[Image(url="https://example.com/one.png")],
        session_id="s1",
    )
    original_user = next(m for m in first.messages if m.images)

    second = agent.run("second turn", session_id="s1")
    history_user = next(m for m in second.messages if m.from_history and m.images)

    # The media-carrying copy must not share media objects with the original:
    # the media-offload refresh mutates image.url in place on the copy.
    assert history_user is not original_user
    assert history_user.images[0] is not original_user.images[0]
    assert history_user.images[0].url == original_user.images[0].url


def test_copy_history_message_deep_copies_list_content():
    # Provider request builders can alias a list-shaped content into the
    # payload they build, so those messages must not share the list
    from agno.models.message import Message
    from agno.utils.message import copy_history_message

    msg = Message(role="user", content=[{"type": "text", "text": "FIRST"}])
    copied = copy_history_message(msg)

    assert copied.from_history is True
    assert msg.from_history is False
    assert copied.content == msg.content
    assert copied.content is not msg.content


def test_copy_history_message_tags_only_the_copy():
    from agno.models.message import Message
    from agno.utils.message import copy_history_message

    msg = Message(role="user", content="hello")
    copied = copy_history_message(msg)

    assert copied is not msg
    assert copied.from_history is True
    assert msg.from_history is False


@pytest.mark.asyncio
async def test_history_tagging_does_not_mutate_cached_messages_async():
    agent = _make_agent()
    first = await agent.arun("first turn", session_id="s1")

    second = await agent.arun("second turn", session_id="s1")

    assert all(m.from_history is False for m in first.messages)
    history = [m for m in second.messages if m.from_history]
    assert len(history) >= 2
    first_ids = {id(m) for m in first.messages}
    assert all(id(m) not in first_ids for m in history)
