import json
from typing import Any, AsyncIterator, Callable, Iterator

import pytest

from agno.learn.config import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.learn.stores.entity_memory import EntityMemoryStore
from agno.learn.stores.learned_knowledge import LearnedKnowledgeStore
from agno.learn.stores.session_context import SessionContextStore
from agno.learn.stores.user_memory import UserMemoryStore
from agno.learn.stores.user_profile import UserProfileStore
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse

DEFAULT_MAX_UPDATES = 10


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingLearningDb:
    def __init__(self) -> None:
        self.write_count = 0

    def get_learning(self, **_: Any) -> None:
        return None

    def upsert_learning(self, **_: Any) -> None:
        self.write_count += 1


class _EmptyKnowledge:
    # LearnedKnowledgeStore.asearch falls back to sync search when the
    # knowledge base has no asearch method, so one method covers both paths
    def search(self, **_: Any) -> list:
        return []


class _LimitCapturingModel:
    """Duck-typed model that captures tool_call_limit without running the real loop."""

    def __init__(self, captured_limits: list[int | None]) -> None:
        self.captured_limits = captured_limits

    def __deepcopy__(self, memo: dict[int, Any]) -> "_LimitCapturingModel":
        return self

    def response(
        self,
        messages: Any = None,
        tools: Any = None,
        tool_call_limit: int | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        self.captured_limits.append(tool_call_limit)
        return ModelResponse(role="assistant", content="No updates needed")

    async def aresponse(
        self,
        messages: Any = None,
        tools: Any = None,
        tool_call_limit: int | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        self.captured_limits.append(tool_call_limit)
        return ModelResponse(role="assistant", content="No updates needed")


class _LoopingAddMemoryModel(Model):
    """Model subclass that exercises the real response loop with repeated tool calls.

    Must inherit Model so extract_and_save runs the actual tool execution pipeline.
    """

    def __init__(self, provider_calls: list[int], tool_call_requests: int) -> None:
        super().__init__(id="looping-add-memory-test", name="looping-add-memory-test", provider="test")
        self.provider_calls = provider_calls
        self.tool_call_requests = tool_call_requests

    def __deepcopy__(self, memo: dict[int, Any]) -> "_LoopingAddMemoryModel":
        # Share mutable state so recorder survives the store's deepcopy
        return type(self)(provider_calls=self.provider_calls, tool_call_requests=self.tool_call_requests)

    def _response_for_call(self) -> ModelResponse:
        call_number = len(self.provider_calls) + 1
        self.provider_calls.append(call_number)

        if call_number <= self.tool_call_requests:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": f"add-memory-{call_number}",
                        "type": "function",
                        "function": {
                            "name": "add_memory",
                            "arguments": json.dumps({"memory": f"Fact {call_number} about the user."}),
                        },
                    }
                ],
            )

        return ModelResponse(role="assistant", content="Memory extraction complete.")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response_for_call()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response_for_call()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("streaming should not be used")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("streaming should not be used")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


# ---------------------------------------------------------------------------
# Store builders
# ---------------------------------------------------------------------------


def _build_session_context_store(model: Any, **config_kwargs: Any) -> tuple[Any, dict[str, str]]:
    # Default max_updates_per_run to 10 if not provided (simulates LearningMachine behavior)
    config_kwargs.setdefault("max_updates_per_run", DEFAULT_MAX_UPDATES)
    store = SessionContextStore(
        config=SessionContextConfig(db=_RecordingLearningDb(), model=model, **config_kwargs)  # type: ignore[arg-type]
    )
    return store, {"session_id": "session-1"}


def _build_user_profile_store(model: Any, **config_kwargs: Any) -> tuple[Any, dict[str, str]]:
    config_kwargs.setdefault("max_updates_per_run", DEFAULT_MAX_UPDATES)
    store = UserProfileStore(
        config=UserProfileConfig(db=_RecordingLearningDb(), model=model, **config_kwargs)  # type: ignore[arg-type]
    )
    return store, {"user_id": "user-1"}


def _build_user_memory_store(model: Any, **config_kwargs: Any) -> tuple[Any, dict[str, str]]:
    config_kwargs.setdefault("max_updates_per_run", DEFAULT_MAX_UPDATES)
    store = UserMemoryStore(
        config=UserMemoryConfig(db=_RecordingLearningDb(), model=model, **config_kwargs)  # type: ignore[arg-type]
    )
    return store, {"user_id": "user-1"}


def _build_entity_memory_store(model: Any, **config_kwargs: Any) -> tuple[Any, dict[str, str]]:
    config_kwargs.setdefault("max_updates_per_run", DEFAULT_MAX_UPDATES)
    store = EntityMemoryStore(
        config=EntityMemoryConfig(db=_RecordingLearningDb(), model=model, **config_kwargs)  # type: ignore[arg-type]
    )
    return store, {"user_id": "user-1"}


def _build_learned_knowledge_store(model: Any, **config_kwargs: Any) -> tuple[Any, dict[str, str]]:
    config_kwargs.setdefault("max_updates_per_run", DEFAULT_MAX_UPDATES)
    store = LearnedKnowledgeStore(
        config=LearnedKnowledgeConfig(knowledge=_EmptyKnowledge(), model=model, **config_kwargs)
    )
    return store, {"user_id": "user-1"}


STORE_BUILDERS = [
    pytest.param(_build_session_context_store, id="session_context"),
    pytest.param(_build_user_profile_store, id="user_profile"),
    pytest.param(_build_user_memory_store, id="user_memory"),
    pytest.param(_build_entity_memory_store, id="entity_memory"),
    pytest.param(_build_learned_knowledge_store, id="learned_knowledge"),
]


# ---------------------------------------------------------------------------
# Config default tests
# ---------------------------------------------------------------------------


@pytest.fixture
def conversation_messages() -> list[Message]:
    return [Message(role="user", content="I live in Lisbon and work at Acme as a data engineer")]


@pytest.mark.parametrize(
    "config_cls",
    [
        pytest.param(UserProfileConfig, id="user_profile"),
        pytest.param(UserMemoryConfig, id="user_memory"),
        pytest.param(SessionContextConfig, id="session_context"),
        pytest.param(LearnedKnowledgeConfig, id="learned_knowledge"),
        pytest.param(EntityMemoryConfig, id="entity_memory"),
    ],
)
def test_config_default_max_updates_per_run(config_cls: type) -> None:
    # Config defaults to None (inherits from LearningMachine)
    assert config_cls().max_updates_per_run is None


# ---------------------------------------------------------------------------
# Limit pass-through tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("build_store", STORE_BUILDERS)
def test_extract_and_save_passes_default_limit(
    build_store: Callable[..., tuple[Any, dict[str, str]]],
    conversation_messages: list[Message],
) -> None:
    captured_limits: list[int | None] = []
    store, extract_kwargs = build_store(_LimitCapturingModel(captured_limits=captured_limits))

    store.extract_and_save(messages=conversation_messages, **extract_kwargs)

    assert captured_limits == [DEFAULT_MAX_UPDATES]


@pytest.mark.parametrize("build_store", STORE_BUILDERS)
async def test_aextract_and_save_passes_default_limit(
    build_store: Callable[..., tuple[Any, dict[str, str]]],
    conversation_messages: list[Message],
) -> None:
    captured_limits: list[int | None] = []
    store, extract_kwargs = build_store(_LimitCapturingModel(captured_limits=captured_limits))

    await store.aextract_and_save(messages=conversation_messages, **extract_kwargs)

    assert captured_limits == [DEFAULT_MAX_UPDATES]


@pytest.mark.parametrize("build_store", STORE_BUILDERS)
def test_extract_and_save_passes_overridden_limit(
    build_store: Callable[..., tuple[Any, dict[str, str]]],
    conversation_messages: list[Message],
) -> None:
    captured_limits: list[int | None] = []
    store, extract_kwargs = build_store(_LimitCapturingModel(captured_limits=captured_limits), max_updates_per_run=2)

    store.extract_and_save(messages=conversation_messages, **extract_kwargs)

    assert captured_limits == [2]


@pytest.mark.parametrize("build_store", STORE_BUILDERS)
async def test_aextract_and_save_passes_overridden_limit(
    build_store: Callable[..., tuple[Any, dict[str, str]]],
    conversation_messages: list[Message],
) -> None:
    captured_limits: list[int | None] = []
    store, extract_kwargs = build_store(_LimitCapturingModel(captured_limits=captured_limits), max_updates_per_run=2)

    await store.aextract_and_save(messages=conversation_messages, **extract_kwargs)

    assert captured_limits == [2]


# ---------------------------------------------------------------------------
# Tool execution enforcement tests (UserMemoryStore as representative)
# ---------------------------------------------------------------------------


def _build_looping_memory_store(
    max_updates_per_run: int, tool_call_requests: int
) -> tuple[UserMemoryStore, _RecordingLearningDb, list[int]]:
    provider_calls: list[int] = []
    db = _RecordingLearningDb()
    store = UserMemoryStore(
        config=UserMemoryConfig(
            db=db,  # type: ignore[arg-type]
            model=_LoopingAddMemoryModel(provider_calls=provider_calls, tool_call_requests=tool_call_requests),
            max_updates_per_run=max_updates_per_run,
        )
    )
    return store, db, provider_calls


def test_all_tool_calls_execute_below_limit(conversation_messages: list[Message]) -> None:
    store, db, provider_calls = _build_looping_memory_store(max_updates_per_run=10, tool_call_requests=4)

    result = store.extract_and_save(messages=conversation_messages, user_id="user-1")

    assert db.write_count == 4
    assert provider_calls == [1, 2, 3, 4, 5]
    assert result == "Memory extraction complete."


def test_extract_and_save_caps_tool_writes_at_limit(conversation_messages: list[Message]) -> None:
    # The limit blocks tool execution, not provider turns — the model keeps being
    # re-invoked until it stops requesting tools (base.py run_function_calls continues)
    store, db, provider_calls = _build_looping_memory_store(max_updates_per_run=2, tool_call_requests=4)

    result = store.extract_and_save(messages=conversation_messages, user_id="user-1")

    assert db.write_count == 2
    assert provider_calls == [1, 2, 3, 4, 5]
    assert store.memories_updated is True
    assert result == "Memory extraction complete."


async def test_aextract_and_save_caps_tool_writes_at_limit(conversation_messages: list[Message]) -> None:
    # Same as sync: limit blocks execution, provider turns continue
    store, db, provider_calls = _build_looping_memory_store(max_updates_per_run=2, tool_call_requests=4)

    result = await store.aextract_and_save(messages=conversation_messages, user_id="user-1")

    assert db.write_count == 2
    assert provider_calls == [1, 2, 3, 4, 5]
    assert store.memories_updated is True
    assert result == "Memory extraction complete."


# ---------------------------------------------------------------------------
# LearningMachine global propagation tests
# ---------------------------------------------------------------------------


def test_learning_machine_propagates_global_limit_to_stores() -> None:
    from agno.learn import LearningMachine

    lm = LearningMachine(
        db=_RecordingLearningDb(),  # type: ignore[arg-type]
        model=_LimitCapturingModel(captured_limits=[]),
        max_updates_per_run=25,
        user_profile=True,
        user_memory=True,
        session_context=True,
        entity_memory=True,
    )

    # Access stores to trigger initialization
    assert lm.user_profile_store is not None
    assert lm.user_memory_store is not None
    assert lm.session_context_store is not None
    assert lm.entity_memory_store is not None

    # Each store should have the global limit
    assert lm.user_profile_store.config.max_updates_per_run == 25
    assert lm.user_memory_store.config.max_updates_per_run == 25
    assert lm.session_context_store.config.max_updates_per_run == 25
    assert lm.entity_memory_store.config.max_updates_per_run == 25


def test_learning_machine_store_override_takes_precedence() -> None:
    from agno.learn import LearningMachine

    lm = LearningMachine(
        db=_RecordingLearningDb(),  # type: ignore[arg-type]
        model=_LimitCapturingModel(captured_limits=[]),
        max_updates_per_run=25,
        user_profile=True,
        # Entity memory explicitly overrides the global
        entity_memory=EntityMemoryConfig(max_updates_per_run=50),
    )

    # user_profile uses global default
    assert lm.user_profile_store.config.max_updates_per_run == 25
    # entity_memory uses its explicit override
    assert lm.entity_memory_store.config.max_updates_per_run == 50


def test_learning_machine_without_global_uses_store_defaults() -> None:
    from agno.learn import LearningMachine

    lm = LearningMachine(
        db=_RecordingLearningDb(),  # type: ignore[arg-type]
        model=_LimitCapturingModel(captured_limits=[]),
        # No max_updates_per_run set
        user_profile=True,
        user_memory=True,
    )

    # Should use the default of 10
    assert lm.user_profile_store.config.max_updates_per_run == DEFAULT_MAX_UPDATES
    assert lm.user_memory_store.config.max_updates_per_run == DEFAULT_MAX_UPDATES
