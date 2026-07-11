"""Extraction stores frame the transcript before sending it to the model."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from agno.learn.config import UserMemoryConfig, UserProfileConfig
from agno.learn.stores.user_memory import UserMemoryStore
from agno.learn.stores.user_profile import UserProfileStore
from agno.models.message import Message

CONVERSATION = [
    Message(role="user", content="My name is Alice and I am a cardiologist."),
    Message(role="assistant", content="Nice to meet you, Alice."),
]


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


def _make_profile_store():
    model = _RecordingModel()
    store = UserProfileStore(config=UserProfileConfig(model=model, db=MagicMock()))
    store.get = MagicMock(return_value=None)
    store.aget = AsyncMock(return_value=None)
    store._get_extraction_tools = MagicMock(return_value=[])
    store._aget_extraction_tools = AsyncMock(return_value=[])
    store._build_functions_for_model = MagicMock(return_value=[])
    store._get_system_message = MagicMock(return_value=Message(role="system", content="sys"))
    return store, model


def _make_memory_store():
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


def test_user_profile_frames_transcript():
    store, model = _make_profile_store()
    store.extract_and_save(messages=CONVERSATION, user_id="u1")

    user_message = model.captured_messages[-1]
    assert user_message.content.startswith("Extract profile information from this conversation:")
    assert "cardiologist" in user_message.content


async def test_user_profile_frames_transcript_async():
    store, model = _make_profile_store()
    await store.aextract_and_save(messages=CONVERSATION, user_id="u1")

    user_message = model.captured_messages[-1]
    assert user_message.content.startswith("Extract profile information from this conversation:")
    assert "cardiologist" in user_message.content


def test_user_memory_frames_transcript():
    store, model = _make_memory_store()
    store.extract_and_save(messages=CONVERSATION, user_id="u1")

    user_message = model.captured_messages[-1]
    assert user_message.content.startswith("Extract memories from this conversation:")
    assert "cardiologist" in user_message.content


async def test_user_memory_frames_transcript_async():
    store, model = _make_memory_store()
    await store.aextract_and_save(messages=CONVERSATION, user_id="u1")

    user_message = model.captured_messages[-1]
    assert user_message.content.startswith("Extract memories from this conversation:")
    assert "cardiologist" in user_message.content
