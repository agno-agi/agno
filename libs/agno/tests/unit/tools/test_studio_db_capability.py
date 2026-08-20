"""Adapters without the component catalog answer db_not_configured.

Most db adapters (InMemory, MySQL, Redis, Mongo, and every async adapter)
inherit component-API stubs that raise NotImplementedError. The control-plane
tools resolve the component and gate ownership BEFORE their try blocks, so
without a guard in those shared helpers the raise escapes the JSON envelope
as a raw traceback. The capability refusal must be the same envelope
everywhere: ok=false, code=db_not_configured.
"""

import asyncio
import json

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.tools.studio import StudioTools


@pytest.fixture
def studio():
    db = InMemoryDb()
    registry = Registry(name="Capability Registry", models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
    return StudioTools(registry=registry, db=db)


def _ctx() -> RunContext:
    return RunContext(run_id="r1", session_id="s1", user_id="user-1")


def _assert_capability_envelope(raw: str) -> None:
    out = json.loads(raw)
    assert out.get("ok") is False, out
    assert out["error"]["code"] == "db_not_configured", out


SYNC_CALLS = [
    ("get_component", ("anything",), {}),
    ("list_versions", ("anything",), {}),
    ("validate_component", ("anything",), {}),
    ("publish_component", ("anything",), {}),
    ("set_current_version", ("anything", 1), {}),
    ("delete_version", ("anything", 1), {}),
]


class TestSyncToolsAnswerTheEnvelope:
    @pytest.mark.parametrize("tool_name,args,kwargs", SYNC_CALLS)
    def test_unscoped(self, studio, tool_name, args, kwargs):
        _assert_capability_envelope(getattr(studio, tool_name)(*args, **kwargs))

    @pytest.mark.parametrize("tool_name,args,kwargs", SYNC_CALLS)
    def test_scoped(self, studio, tool_name, args, kwargs):
        # The ownership gate runs only for a scoped caller, so the scoped path
        # exercises a different unguarded statement than the unscoped one.
        _assert_capability_envelope(getattr(studio, tool_name)(*args, _agno_run_context=_ctx(), **kwargs))


class TestAsyncTwinsAnswerTheEnvelope:
    @pytest.mark.parametrize("tool_name,args,kwargs", SYNC_CALLS)
    def test_scoped(self, studio, tool_name, args, kwargs):
        result = asyncio.run(getattr(studio, "a" + tool_name)(*args, _agno_run_context=_ctx(), **kwargs))
        _assert_capability_envelope(result)


class TestVersionPinnedRunsAnswerTheEnvelope:
    def test_run_agent_with_a_version_pin(self, studio):
        out = json.loads(studio.run_agent("anything", message="hi", version=1, _agno_run_context=_ctx()))
        assert "error" in out or out.get("ok") is False, out

    def test_arun_agent_with_a_version_pin(self, studio):
        out = json.loads(asyncio.run(studio.arun_agent("anything", message="hi", version=1, _agno_run_context=_ctx())))
        assert "error" in out or out.get("ok") is False, out


class TestAsyncAdaptersAnswerTheEnvelope:
    def test_async_sqlite_is_a_capability_refusal_too(self, tmp_path):
        db = AsyncSqliteDb(id="cap-async", db_file=str(tmp_path / "cap.db"))
        registry = Registry(name="Async Capability", models=[OpenAIResponses(id="gpt-5.5")], dbs=[])
        studio = StudioTools(registry=registry, db=db)  # type: ignore[arg-type]

        _assert_capability_envelope(studio.get_component("anything"))
        _assert_capability_envelope(studio.publish_component("anything", _agno_run_context=_ctx()))
