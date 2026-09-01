"""Extraction stores frame the transcript before sending it to the model."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.learn.config import UserMemoryConfig, UserProfileConfig
from agno.learn.stores.user_memory import UserMemoryStore
from agno.learn.stores.user_profile import UserProfileStore
from agno.models.message import Message


class _RecordingModel:
    """Fake model that survives deepcopy and records the messages it receives."""

    def __init__(self):
        self.captured_messages = None

    def __deepcopy__(self, memo):
        return self

    def _record(self, messages):
        self.captured_messages = messages
        return SimpleNamespace(content="", tool_executions=[], response_usage=None)

    def response(self, messages, tools=None, **kwargs):
        return self._record(messages)

    async def aresponse(self, messages, tools=None, **kwargs):
        return self._record(messages)


@pytest.fixture
def conversation():
    """Sample conversation for extraction tests."""
    return [
        Message(role="user", content="My name is Alice and I am a cardiologist."),
        Message(role="assistant", content="Nice to meet you, Alice."),
    ]


@pytest.fixture
def profile_store_and_model():
    """UserProfileStore with recording model."""
    model = _RecordingModel()
    store = UserProfileStore(config=UserProfileConfig(model=model, db=MagicMock()))
    store.get = MagicMock(return_value=None)
    store.aget = AsyncMock(return_value=None)
    store._get_extraction_tools = MagicMock(return_value=[])
    store._aget_extraction_tools = AsyncMock(return_value=[])
    store._build_functions_for_model = MagicMock(return_value=[])
    store._get_system_message = MagicMock(return_value=Message(role="system", content="sys"))
    return store, model


@pytest.fixture
def memory_store_and_model():
    """UserMemoryStore with recording model."""
    model = _RecordingModel()
    store = UserMemoryStore(config=UserMemoryConfig(model=model, db=MagicMock()))
    store.get = MagicMock(return_value=[])
    store.aget = AsyncMock(return_value=[])
    store._memories_to_list = MagicMock(return_value=[])
    store._get_extraction_tools = MagicMock(return_value=[])
    store._aget_extraction_tools = AsyncMock(return_value=[])
    store._build_functions_for_model = MagicMock(return_value=[])
    store._get_system_message = MagicMock(return_value=Message(role="system", content="sys"))
    return store, model


def test_user_profile_frames_transcript_sync(profile_store_and_model, conversation):
    store, model = profile_store_and_model
    store.extract_and_save(messages=conversation, user_id="u1")

    user_message = model.captured_messages[-1]
    assert user_message.content.startswith("Extract profile information from this conversation:\n\n")
    assert "cardiologist" in user_message.content


async def test_user_profile_frames_transcript_async(profile_store_and_model, conversation):
    store, model = profile_store_and_model
    await store.aextract_and_save(messages=conversation, user_id="u1")

    user_message = model.captured_messages[-1]
    assert user_message.content.startswith("Extract profile information from this conversation:\n\n")
    assert "cardiologist" in user_message.content


def test_user_memory_frames_transcript_sync(memory_store_and_model, conversation):
    store, model = memory_store_and_model
    store.extract_and_save(messages=conversation, user_id="u1")

    user_message = model.captured_messages[-1]
    assert user_message.content.startswith("Extract memories from this conversation:\n\n")
    assert "cardiologist" in user_message.content


async def test_user_memory_frames_transcript_async(memory_store_and_model, conversation):
    store, model = memory_store_and_model
    await store.aextract_and_save(messages=conversation, user_id="u1")

    user_message = model.captured_messages[-1]
    assert user_message.content.startswith("Extract memories from this conversation:\n\n")
    assert "cardiologist" in user_message.content
