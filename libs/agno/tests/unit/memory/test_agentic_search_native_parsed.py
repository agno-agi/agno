"""Agentic memory search must keep a native structured-output result. The unconditional
content re-parse clobbered it: a native provider returning a valid `parsed` plus
natural-language `content` had its good result overwritten (and dropped to [])."""

from typing import Any

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.memory.manager import MemoryManager, MemorySearchResponse, UserMemory
from agno.models.base import Model
from agno.models.response import ModelResponse


def _model(parsed, content, native=True):
    class _M(Model):
        def __init__(self):
            super().__init__(id="m", name="m", provider="t")
            self.supports_native_structured_outputs = native

        def response(self, messages=None, response_format=None, **kwargs):
            r = ModelResponse(role="assistant")
            r.parsed = parsed
            r.content = content
            return r

        def invoke(self, *a, **k):
            return None

        async def ainvoke(self, *a, **k):
            return None

        def invoke_stream(self, *a, **k):
            yield None

        async def ainvoke_stream(self, *a, **k):
            yield None
            return

        def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
            return ModelResponse(role="assistant")

        def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
            return ModelResponse(role="assistant")

    return _M()


def _search(model):
    manager = MemoryManager(model=model, db=InMemoryDb())
    manager.read_from_db = lambda user_id=None: {"u1": [UserMemory(memory_id="m1", memory="A", user_id="u1")]}
    return [m.memory_id for m in manager._search_user_memories_agentic(user_id="u1", query="q")]


def test_native_parsed_with_natural_language_content_is_kept():
    result = _search(_model(MemorySearchResponse(memory_ids=["m1"]), "I found it for you."))
    assert result == ["m1"]


def test_native_parsed_with_empty_content_is_kept():
    result = _search(_model(MemorySearchResponse(memory_ids=["m1"]), ""))
    assert result == ["m1"]
