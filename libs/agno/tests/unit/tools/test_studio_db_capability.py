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
        _assert_capability_envelope(studio.run_agent("anything", message="hi", version=1, _agno_run_context=_ctx()))

    def test_arun_agent_with_a_version_pin(self, studio):
        _assert_capability_envelope(
            asyncio.run(studio.arun_agent("anything", message="hi", version=1, _agno_run_context=_ctx()))
        )


class TestAuthoringToolsAnswerTheEnvelope:
    def test_create_agent(self, studio):
        _assert_capability_envelope(studio.create_agent(name="X", instructions="i", _agno_run_context=_ctx()))

    def test_edit_agent(self, studio):
        # The edit path resolves the target through its own lenient lookup,
        # which maps the missing catalog to not-found rather than the
        # capability code; either way it must be an envelope, not a raise.
        out = json.loads(studio.edit_agent("anything", instructions="i", _agno_run_context=_ctx()))
        assert out.get("ok") is False, out
        assert out["error"]["code"] in ("db_not_configured", "component_not_found"), out


class TestPartialAdaptersAnswerTheEnvelope:
    def test_list_versions_on_an_adapter_without_list_configs(self, tmp_path):
        # An adapter can implement the component row API but not list_configs;
        # list_versions' own guard has to answer the envelope then, because
        # the shared resolver has already succeeded.
        from agno.db.sqlite import SqliteDb

        class NoListConfigsDb(SqliteDb):
            def list_configs(self, *args, **kwargs):
                raise NotImplementedError("no list_configs")

        db = NoListConfigsDb(id="partial", db_file=str(tmp_path / "partial.db"))
        db.create_component_with_config(
            component_id="c",
            component_type=__import__("agno.db.base", fromlist=["ComponentType"]).ComponentType.AGENT,
            name="c",
            config={"name": "c"},
            stage="published",
        )
        registry = Registry(name="Partial", models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
        studio = StudioTools(registry=registry, db=db)

        _assert_capability_envelope(studio.list_versions("c"))


class TestAsyncAdaptersAnswerTheEnvelope:
    def test_async_sqlite_is_a_capability_refusal_too(self, tmp_path):
        db = AsyncSqliteDb(id="cap-async", db_file=str(tmp_path / "cap.db"))
        registry = Registry(name="Async Capability", models=[OpenAIResponses(id="gpt-5.5")], dbs=[])
        studio = StudioTools(registry=registry, db=db)  # type: ignore[arg-type]

        _assert_capability_envelope(studio.get_component("anything"))
        _assert_capability_envelope(studio.publish_component("anything", _agno_run_context=_ctx()))
