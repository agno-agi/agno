import json
from typing import Any, AsyncIterator, Iterator

import pytest

from agno.learn.config import SessionContextConfig
from agno.learn.stores.session_context import SessionContextStore
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse


class RecordingLearningDb:
    def __init__(self) -> None:
        self.write_count = 0

    def get_learning(self, **_: Any) -> None:
        return None

    def upsert_learning(self, **_: Any) -> None:
        self.write_count += 1


class SingleSaveToolModel(Model):
    def __init__(self, provider_calls: list[int], planning: bool) -> None:
        super().__init__(id="session-context-test", name="session-context-test", provider="test")
        self.provider_calls = provider_calls
        self.planning = planning

    def __deepcopy__(self, memo: dict[int, Any]) -> "SingleSaveToolModel":
        return type(self)(provider_calls=self.provider_calls, planning=self.planning)

    def _response_for_call(self) -> ModelResponse:
        call_number = len(self.provider_calls) + 1
        self.provider_calls.append(call_number)

        if call_number == 1:
            arguments: dict[str, Any] = {"summary": "The user is testing session context extraction."}
            if self.planning:
                arguments.update(
                    goal="Verify session context extraction",
                    plan=["Save the session context"],
                    progress=[],
                )

            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "save-session-context",
                        "type": "function",
                        "function": {
                            "name": "save_session_context",
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
            )

        return ModelResponse(role="assistant", content="Session context saved.")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response_for_call()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response_for_call()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._response_for_call()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._response_for_call()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def build_store(planning: bool) -> tuple[SessionContextStore, RecordingLearningDb, list[int]]:
    provider_calls: list[int] = []
    db = RecordingLearningDb()
    store = SessionContextStore(
        config=SessionContextConfig(
            db=db,  # type: ignore[arg-type]
            model=SingleSaveToolModel(provider_calls=provider_calls, planning=planning),
            enable_planning=planning,
        )
    )
    return store, db, provider_calls


@pytest.mark.parametrize("planning", [False, True])
def test_extract_and_save_stops_after_save_tool(planning: bool) -> None:
    store, db, provider_calls = build_store(planning=planning)

    result = store.extract_and_save(
        messages=[Message(role="user", content="Remember the current task")],
        session_id="session-1",
    )

    assert provider_calls == [1]
    assert db.write_count == 1
    assert store.context_updated is True
    assert result == "Context updated"


@pytest.mark.asyncio
@pytest.mark.parametrize("planning", [False, True])
async def test_aextract_and_save_stops_after_save_tool(planning: bool) -> None:
    store, db, provider_calls = build_store(planning=planning)

    result = await store.aextract_and_save(
        messages=[Message(role="user", content="Remember the current task")],
        session_id="session-1",
    )

    assert provider_calls == [1]
    assert db.write_count == 1
    assert store.context_updated is True
    assert result == "Context updated"
