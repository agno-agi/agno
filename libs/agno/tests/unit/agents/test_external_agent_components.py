"""External agents (ClaudeAgent, CodexAgent) stored and served as agent components.

A stored config carries the adapter's settings plus references the registry
resolves on load: the db, the sandbox and a Pydantic output schema. The db
loaders rebuild the adapter the config names, AgentOS lists and runs it, and
the composition surfaces refuse it where an Agent is required.
"""

import asyncio
import tempfile
import warnings
from pathlib import Path
from typing import Any, AsyncIterator, ClassVar, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agno.agent import Agent, get_agent_by_id, get_agents
from agno.agents import _storage
from agno.agents._config import agent_dataclass
from agno.agents.base import BaseExternalAgent
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.os import AgentOS
from agno.os.routers.components import get_components_router
from agno.os.routers.registry import get_registry_router
from agno.os.settings import AgnoAPISettings
from agno.os.utils import collect_components_from_os
from agno.registry import Registry
from agno.run.agent import RunContentEvent, RunEvent, RunOutputEvent
from agno.sandbox import Sandbox
from agno.sandbox.repository import Repository
from agno.team import Team
from agno.workflow import Workflow


class Answer(BaseModel):
    answer: str


class FakeSandbox(Sandbox):
    def __init__(self, id: Optional[str] = None, env: Optional[Dict[str, str]] = None, network: str = "isolated"):
        self.id = id
        self.env = env
        self.network = network

    async def acreate(self, session_id, *, agent_id=None, generation=1, env=None):
        raise NotImplementedError

    async def aget(self, provider_ref):
        raise NotImplementedError

    async def aexec(self, handle, command, **kwargs):
        raise NotImplementedError

    async def astop(self, handle):
        raise NotImplementedError

    async def adestroy(self, handle):
        raise NotImplementedError


@agent_dataclass
class EchoAgent(BaseExternalAgent):
    """A storable adapter with no SDK behind it, so stored configs can be run end to end."""

    greeting: str = "echo"

    _sdk_name: ClassVar[str] = "echo"
    _storable: ClassVar[bool] = True

    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        return f"{self.greeting}: {input}"

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        yield RunContentEvent(run_id=kwargs.get("run_id", ""), content=f"{self.greeting}: {input}")


@agent_dataclass
class OpaqueAgent(BaseExternalAgent):
    """An adapter whose settings are not plain data; it is not storable."""

    _sdk_name: ClassVar[str] = "opaque"

    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        return input

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        yield RunContentEvent(run_id=kwargs.get("run_id", ""), content=input)


@pytest.fixture
def db() -> SqliteDb:
    tmp = tempfile.mkdtemp()
    return SqliteDb(id="components-db", db_file=f"{tmp}/components.db")


@pytest.fixture
def sandbox() -> FakeSandbox:
    return FakeSandbox(id="docker-local")


@pytest.fixture
def registry(db, sandbox) -> Registry:
    return Registry(dbs=[db], schemas=[Answer], sandboxes=[sandbox], allow_host_external_agents=True)


@pytest.fixture
def agno_logs(caplog):
    """caplog with the Agno loggers attached: they do not propagate to the root logger."""
    import logging

    loggers = [logging.getLogger(name) for name in ("agno", "agno-team", "agno-workflow")]
    for logger in loggers:
        logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        for logger in loggers:
            logger.removeHandler(caplog.handler)


@pytest.fixture
def echo_storable(monkeypatch):
    monkeypatch.setitem(_storage.STORABLE_ADAPTERS, "echo", (__name__, "EchoAgent"))


# ---------------------------------------------------------------------------
# to_dict / from_dict
# ---------------------------------------------------------------------------


class TestClaudeSerialization:
    def test_settings_round_trip(self, db, registry):
        agent = ClaudeAgent(
            id="coder",
            name="Coder",
            description="Writes code",
            role="Implements the change a leader delegates",
            db=db,
            model="claude-opus-4-6",
            system_prompt={"type": "preset", "preset": "claude_code", "append": "Be brief."},
            cwd=Path("/tmp/work"),
            keep_uploads=True,
            setting_sources=["project"],
            tools=["Read", "Edit"],
            allowed_tools=["Read"],
            disallowed_tools=["Bash"],
            permission_mode="acceptEdits",
            mcp_servers={"docs": {"type": "stdio", "command": "docs-server", "args": ["--port", "1"]}},
            strict_mcp_config=True,
            skills=["review"],
            plugins=[{"type": "local", "path": "/tmp/plugin"}],
            max_turns=4,
            max_budget_usd=1.5,
            output_schema=Answer,
            markdown=False,
            retries=2,
            delay_between_retries=3,
            exponential_backoff=True,
            require_native_resume=True,
            strict_persistence=True,
            store_events=True,
            events_to_skip=[RunEvent.run_started],
        )

        config = agent.to_dict()

        assert config["sdk"] == "claude-agent-sdk"
        assert config["cwd"] == "/tmp/work"
        assert config["role"] == "Implements the change a leader delegates"
        assert config["output_schema"] == "Answer"
        assert config["events_to_skip"] == ["RunStarted"]
        assert config["db"]["id"] == "components-db"
        assert "sandbox" not in config
        rebuilt = ClaudeAgent.from_dict(config, registry=registry, strict=True)
        assert rebuilt.db is db
        assert rebuilt.output_schema is Answer
        assert rebuilt.events_to_skip == [RunEvent.run_started]
        assert rebuilt.to_dict() == config

    def test_base_class_dispatches_on_sdk(self, registry):
        config = ClaudeAgent(id="coder", permission_mode="plan").to_dict()

        rebuilt = BaseExternalAgent.from_dict(config, registry=registry, strict=True)

        assert type(rebuilt) is ClaudeAgent
        assert rebuilt.permission_mode == "plan"

    def test_sandbox_and_repository_are_stored_by_reference(self, registry, sandbox):
        agent = ClaudeAgent(
            id="coder", sandbox=sandbox, repository=Repository(url="https://github.com/agno-agi/agno", branch="dev")
        )

        config = agent.to_dict()

        assert config["sandbox"] == {"id": "docker-local"}
        assert config["repository"] == {"url": "https://github.com/agno-agi/agno", "branch": "dev"}
        rebuilt = ClaudeAgent.from_dict(config, registry=registry, strict=True)
        assert rebuilt.sandbox is sandbox
        assert rebuilt.repository == Repository(url="https://github.com/agno-agi/agno", branch="dev")

    def test_defaults_are_not_stored(self):
        config = ClaudeAgent(id="coder").to_dict()

        # The model default and the project key are set at construction, so they round-trip explicitly.
        assert config == {
            "sdk": "claude-agent-sdk",
            "id": "coder",
            "model": "claude-sonnet-4-6",
            "project_key": "coder",
        }

    def test_native_options_are_refused(self, monkeypatch):
        from dataclasses import dataclass
        from types import ModuleType

        from agno.agents.claude import agent as claude_module

        @dataclass
        class ClaudeAgentOptions:
            max_turns: Optional[int] = None
            resume: Optional[str] = None

        module = ModuleType("claude_agent_sdk")
        module.ClaudeAgentOptions = ClaudeAgentOptions  # type: ignore[attr-defined]
        monkeypatch.setattr(claude_module, "_sdk", lambda: module)

        agent = ClaudeAgent(id="coder", options=ClaudeAgentOptions(max_turns=2))
        with pytest.raises(ValueError, match="ClaudeAgent.options cannot be stored"):
            agent.to_dict()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            legacy = ClaudeAgent(id="coder", options_kwargs={"max_turns": 2})
        with pytest.raises(ValueError, match="ClaudeAgent.options_kwargs cannot be stored"):
            legacy.to_dict()

    def test_live_objects_in_settings_are_refused(self):
        class Server:
            pass

        agent = ClaudeAgent(id="coder", mcp_servers={"live": {"type": "sdk", "name": "live", "instance": Server()}})

        with pytest.raises(ValueError, match="ClaudeAgent.mcp_servers cannot be stored"):
            agent.to_dict()

    def test_sandbox_without_id_is_refused(self):
        agent = ClaudeAgent(id="coder", sandbox=FakeSandbox())

        with pytest.raises(ValueError, match="sandbox has no id"):
            agent.to_dict()

    def test_wrong_sdk_is_refused_on_an_adapter(self, registry):
        config = CodexAgent(id="cx").to_dict()

        with pytest.raises(ComponentRehydrationError, match="stored for sdk 'codex', not for ClaudeAgent"):
            ClaudeAgent.from_dict(config, registry=registry, strict=True)

    def test_agent_config_is_refused_on_an_adapter(self, db, registry):
        Agent(id="native", name="Native", instructions="Important instructions", db=db).save()

        with pytest.raises(ComponentRehydrationError, match="carries no sdk, so it is stored for an Agent"):
            ClaudeAgent.load("native", db=db, registry=registry)
        with pytest.raises(ComponentRehydrationError, match="carries no sdk"):
            ClaudeAgent.from_dict({"id": "native", "instructions": "Important instructions"}, registry=registry)

    def test_unknown_sdk_is_refused(self, registry):
        with pytest.raises(ComponentRehydrationError, match="No external agent adapter stores configs with sdk 'nope'"):
            BaseExternalAgent.from_dict({"sdk": "nope", "id": "x"}, registry=registry)

    def test_unknown_settings_strict_and_lenient(self, registry, agno_logs):
        config = {"sdk": "claude-agent-sdk", "id": "coder", "permision_mode": "plan"}

        with pytest.raises(ComponentRehydrationError, match=r"does not accept: \['permision_mode'\]"):
            ClaudeAgent.from_dict(config, registry=registry, strict=True)

        rebuilt = ClaudeAgent.from_dict(config, registry=registry, strict=False)
        assert rebuilt.permission_mode is None
        assert "permision_mode" in agno_logs.text

    def test_missing_sandbox_strict_and_lenient(self, db, agno_logs):
        config = {
            "sdk": "claude-agent-sdk",
            "id": "coder",
            "sandbox": {"id": "missing"},
            "repository": {"url": "https://github.com/agno-agi/agno", "branch": "main"},
        }
        empty = Registry(dbs=[db])

        with pytest.raises(ComponentRehydrationError, match="references sandbox 'missing'"):
            ClaudeAgent.from_dict(config, registry=empty, strict=True)

        rebuilt = ClaudeAgent.from_dict(config, registry=empty, strict=False)
        assert rebuilt.sandbox is None
        assert rebuilt.repository is None
        assert "Sandbox 'missing' not found" in agno_logs.text

    def test_missing_schema_strict_and_lenient(self, db):
        config = {"sdk": "claude-agent-sdk", "id": "coder", "output_schema": "Missing"}
        empty = Registry(dbs=[db])

        with pytest.raises(ComponentRehydrationError, match="output schema 'Missing'"):
            ClaudeAgent.from_dict(config, registry=empty, strict=True)
        assert ClaudeAgent.from_dict(config, registry=empty, strict=False).output_schema is None

    def test_unknown_event_is_refused(self, registry):
        config = {"sdk": "claude-agent-sdk", "id": "coder", "events_to_skip": ["NotAnEvent"]}

        with pytest.raises(ComponentRehydrationError, match="unknown event"):
            ClaudeAgent.from_dict(config, registry=registry)

    def test_construction_errors_become_rehydration_errors(self, registry):
        config = {"sdk": "codex", "id": "cx", "require_native_resume": True, "thread_options": {"ephemeral": True}}

        with pytest.raises(ComponentRehydrationError, match="could not be rebuilt from its config"):
            BaseExternalAgent.from_dict(config, registry=registry, strict=True)


class TestCodexSerialization:
    def test_settings_round_trip(self, db, registry):
        agent = CodexAgent(
            id="cx",
            name="Codex",
            db=db,
            model="gpt-5.6-luna",
            instructions="Keep diffs small.",
            base_instructions="You are Codex.",
            model_provider="openai",
            reasoning_effort="high",
            service_tier="fast",
            mcp_servers={"docs": {"command": "docs-server"}},
            cwd="/tmp/work",
            keep_uploads=True,
            sandbox_mode="workspace-write",
            approval_mode="auto_review",
            ephemeral=False,
            thread_options={"personality": "friendly"},
            turn_options={"summary": "concise"},
            config={"model_reasoning_summary": "auto"},
            output_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        )

        config = agent.to_dict()

        assert config["sdk"] == "codex"
        assert config["output_schema"] == {"type": "object", "properties": {"answer": {"type": "string"}}}
        rebuilt = CodexAgent.from_dict(config, registry=registry, strict=True)
        assert rebuilt.db is db
        assert rebuilt.to_dict() == config

    def test_deprecated_kwargs_are_stored_as_options(self, registry):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            agent = CodexAgent(id="cx", thread_kwargs={"ephemeral": True}, turn_kwargs={"effort": "low"})

        config = agent.to_dict()

        assert "thread_kwargs" not in config and "turn_kwargs" not in config
        assert config["thread_options"] == {"ephemeral": True}
        assert config["turn_options"] == {"effort": "low"}
        rebuilt = CodexAgent.from_dict(config, registry=registry, strict=True)
        assert rebuilt.thread_options == {"ephemeral": True}
        assert rebuilt.turn_kwargs == {}

    @pytest.mark.parametrize(
        "settings, field",
        [
            ({"env": {"OPENAI_API_KEY": "secret"}}, "env"),
            ({"codex_bin": "/usr/local/bin/codex"}, "codex_bin"),
        ],
    )
    def test_host_process_settings_are_refused(self, settings, field):
        agent = CodexAgent(id="cx", **settings)

        with pytest.raises(ValueError, match=f"CodexAgent.{field} cannot be stored"):
            agent.to_dict()

    def test_client_options_are_refused(self):
        agent = CodexAgent(id="cx", client_options=object())  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="CodexAgent.client_options cannot be stored"):
            agent.to_dict()


class TestOtherAdapters:
    def test_unstorable_adapter_refuses_to_dict(self):
        with pytest.raises(NotImplementedError, match="OpaqueAgent cannot be stored"):
            OpaqueAgent(id="opaque").to_dict()

    def test_storable_custom_adapter_round_trips(self, echo_storable, registry):
        config = EchoAgent(id="echo", greeting="hi").to_dict()

        assert config == {"sdk": "echo", "id": "echo", "greeting": "hi"}
        rebuilt = BaseExternalAgent.from_dict(config, registry=registry, strict=True)
        assert type(rebuilt) is EchoAgent and rebuilt.greeting == "hi"


# ---------------------------------------------------------------------------
# save / load and the db loaders
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_and_load(self, db, registry):
        agent = ClaudeAgent(id="coder", name="Coder", permission_mode="acceptEdits", output_schema=Answer)

        assert agent.save(db=db) == 1
        assert agent.save(db=db, label="v2") == 2

        loaded = ClaudeAgent.load("coder", db=db, registry=registry, strict=True)
        assert isinstance(loaded, ClaudeAgent)
        assert loaded.permission_mode == "acceptEdits"
        assert loaded.output_schema is Answer
        # The config carried no db, so the loader's db is the fallback.
        assert loaded.db is db
        row = db.get_component("coder")
        assert row["component_type"] == ComponentType.AGENT.value
        assert row["name"] == "Coder"

    def test_delete(self, db):
        agent = ClaudeAgent(id="coder", db=db)
        agent.save()

        assert agent.delete() is True
        assert db.get_component("coder") is None

    @pytest.mark.asyncio
    async def test_async_save_load_delete(self, db, registry):
        agent = ClaudeAgent(id="coder", permission_mode="plan", db=db)

        assert await agent.asave() == 1
        loaded = await ClaudeAgent.aload("coder", db=db, registry=registry, strict=True)
        assert isinstance(loaded, ClaudeAgent) and loaded.permission_mode == "plan"
        assert await agent.adelete() is True
        assert db.get_component("coder") is None

    @pytest.mark.asyncio
    async def test_async_variants_keep_an_in_memory_sqlite_database(self, registry):
        # An in-memory SQLite database is private to each thread, so the async
        # variants must not move its work to a worker thread.
        memory_db = SqliteDb(id="memory-db", db_url="sqlite:///:memory:")
        agent = ClaudeAgent(id="coder", permission_mode="plan", db=memory_db)
        agent.save()

        loaded = await ClaudeAgent.aload("coder", db=memory_db, registry=registry)
        assert isinstance(loaded, ClaudeAgent) and loaded.permission_mode == "plan"
        assert await agent.asave() == 2
        assert memory_db.get_component("coder")["current_version"] == 2
        assert await agent.adelete() is True
        assert memory_db.get_component("coder") is None

    def test_get_agent_by_id_rebuilds_the_adapter(self, db, registry):
        CodexAgent(id="cx", sandbox_mode="read-only").save(db=db)

        loaded = get_agent_by_id(db=db, id="cx", registry=registry, strict=True)

        assert isinstance(loaded, CodexAgent)
        assert loaded.id == "cx"
        assert loaded.sandbox_mode == "read-only"
        assert loaded.db is db

    def test_get_agents_lists_adapters_with_native_agents(self, db, registry):
        Agent(id="native", name="Native", db=db).save()
        ClaudeAgent(id="coder").save(db=db)

        agents = get_agents(db=db, registry=registry)

        by_id = {agent.id: agent for agent in agents}
        assert isinstance(by_id["native"], Agent)
        assert isinstance(by_id["coder"], ClaudeAgent)
        assert by_id["coder"]._version == 1
        assert by_id["coder"]._stage == "published"

    def test_save_refuses_to_change_what_an_id_loads_as(self, db):
        ClaudeAgent(id="coder").save(db=db)

        with pytest.raises(ValueError, match="stored as a 'claude-agent-sdk' external agent; saving an Agent"):
            Agent(id="coder", name="Coder", db=db).save()
        with pytest.raises(ValueError, match="saving a 'codex' external agent under the same id"):
            CodexAgent(id="coder").save(db=db)
        # The same adapter keeps versioning normally.
        assert ClaudeAgent(id="coder", permission_mode="plan").save(db=db) == 2

        Agent(id="native", name="Native", db=db).save()
        with pytest.raises(ValueError, match="stored as an Agent; saving a 'claude-agent-sdk' external agent"):
            ClaudeAgent(id="native").save(db=db)

    def test_adapter_table_keys_are_adapter_parameters_only(self):
        import inspect

        from agno.db.base import BaseDb
        from agno.db.postgres import AsyncPostgresDb, PostgresDb
        from agno.db.utils import ADAPTER_TABLE_NAME_KEYS, DB_TABLE_NAME_KEYS

        base_params = set(inspect.signature(BaseDb.__init__).parameters)
        for key in ADAPTER_TABLE_NAME_KEYS:
            assert key not in base_params and key not in DB_TABLE_NAME_KEYS
            assert key in inspect.signature(PostgresDb.__init__).parameters
            assert key in inspect.signature(AsyncPostgresDb.__init__).parameters

    def test_registry_db_clone_keeps_the_sandbox_bindings_table(self):
        from agno.db.postgres import PostgresDb

        url = "postgresql+psycopg://ai:ai@127.0.0.1:1/none"
        registered = PostgresDb(id="pg", db_url=url)
        registry = Registry(dbs=[registered])
        stored = ClaudeAgent(id="coder", db=PostgresDb(id="pg", db_url=url, sandbox_table="custom_bindings")).to_dict()

        rebuilt = ClaudeAgent.from_dict(stored, registry=registry, strict=True)

        # The override is honoured on a clone that shares the registered engine.
        assert rebuilt.db.sandbox_table_name == "custom_bindings"
        assert rebuilt.db is not registered
        assert rebuilt.db.db_engine is registered.db_engine
        same = ClaudeAgent.from_dict(ClaudeAgent(id="coder", db=registered).to_dict(), registry=registry, strict=True)
        assert same.db is registered

    def test_agent_loaders_refuse_an_external_config(self, db, registry):
        ClaudeAgent(id="coder").save(db=db)

        with pytest.raises(ComponentRehydrationError, match="cannot be loaded as an Agent"):
            Agent.load("coder", db=db, registry=registry, strict=True)
        with pytest.raises(ComponentRehydrationError, match="cannot be loaded as an Agent"):
            Agent.from_dict({"sdk": "codex", "id": "cx"})

    def test_strict_load_of_a_sandboxed_agent_needs_postgres(self, db, registry, sandbox):
        # The config carries no db, so the sqlite loader db is the fallback the sandbox cannot use.
        ClaudeAgent(id="coder", sandbox=sandbox).save(db=db)

        with pytest.raises(ComponentRehydrationError, match="cannot run in its sandbox"):
            get_agent_by_id(db=db, id="coder", registry=registry, strict=True)
        lenient = get_agent_by_id(db=db, id="coder", registry=registry, strict=False)
        assert isinstance(lenient, ClaudeAgent) and lenient.sandbox is sandbox

    def test_caller_metadata_is_kept_on_the_run_output(self, db):
        agent = EchoAgent(id="echo", db=db)
        metadata = {"agno_component_version": 1, "ticket": "T-1"}

        run = agent.run("hi", session_id="s1", metadata=metadata)
        list(agent.run("hi", session_id="s1", stream=True, metadata=metadata))

        assert run.metadata == metadata
        assert run.metadata is not metadata
        # Both the non-streaming and the streaming run keep it on the stored row.
        assert [stored.metadata for stored in db.get_runs(session_id="s1")] == [metadata, metadata]

    def test_turns_in_flight_are_shared_per_agent_and_store(self, db):
        other_db = SqliteDb(id="other-db", db_file=f"{tempfile.mkdtemp()}/other.db")
        first = EchoAgent(id="shared", db=db)
        second = EchoAgent(id="shared", db=db)
        first._sessions_in_flight["s1"] = "run-1"
        try:
            assert second._sessions_in_flight == {"s1": "run-1"}
            assert EchoAgent(id="other", db=db)._sessions_in_flight == {}
            # The same id on another store is another agent's conversation.
            assert EchoAgent(id="shared", db=other_db)._sessions_in_flight == {}
            assert EchoAgent(id="shared")._sessions_in_flight == {}
        finally:
            first._sessions_in_flight.clear()

    def test_same_id_agents_on_different_stores_run_concurrently(self, db):
        other_db = SqliteDb(id="other-db", db_file=f"{tempfile.mkdtemp()}/other.db")
        first = EchoAgent(id="assistant", db=db)
        second = EchoAgent(id="assistant", db=other_db)

        async def both() -> list:
            return await asyncio.gather(
                first.arun("hi", session_id="session-1"), second.arun("hi", session_id="session-1")
            )

        runs = asyncio.run(both())

        assert [run.content for run in runs] == ["echo: hi", "echo: hi"]


# ---------------------------------------------------------------------------
# Composition refuses external agents
# ---------------------------------------------------------------------------


class TestComposition:
    def test_team_from_dict_refuses_a_stored_external_member(self, db, registry, agno_logs):
        ClaudeAgent(id="coder").save(db=db)
        config = {"id": "crew", "name": "Crew", "members": [{"type": "agent", "agent_id": "coder"}]}

        with pytest.raises(ComponentRehydrationError, match="external agents cannot be team members"):
            Team.from_dict(config, db=db, registry=registry, strict=True)

        team = Team.from_dict(config, db=db, registry=registry, strict=False)
        assert team.members == []
        assert "cannot be team members" in agno_logs.text

    def test_team_from_dict_refuses_a_registry_external_member(self, db):
        registry = Registry(agents=[ClaudeAgent(id="coder")])
        config = {"id": "crew", "name": "Crew", "members": [{"type": "agent", "agent_id": "coder"}]}

        with pytest.raises(ComponentRehydrationError, match="external agents cannot be team members"):
            Team.from_dict(config, db=db, registry=registry, strict=True)

    def test_workflow_from_dict_refuses_a_stored_external_step(self, db, registry):
        ClaudeAgent(id="coder").save(db=db)
        config = {
            "id": "wf",
            "name": "WF",
            "steps": [{"type": "Step", "name": "code", "step_id": "code", "agent_id": "coder"}],
        }

        with pytest.raises(ComponentRehydrationError, match="external agents cannot be workflow steps"):
            Workflow.from_dict(config, db=db, registry=registry, strict=True)

    @pytest.fixture
    def components_client(self, db, registry) -> TestClient:
        app = FastAPI()
        app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings(), registry=registry))
        return TestClient(app)

    def test_components_api_refuses_a_stored_external_member(self, db, components_client):
        ClaudeAgent(id="coder").save(db=db)

        response = components_client.post(
            "/components",
            json={
                "name": "crew",
                "component_id": "crew",
                "component_type": "team",
                "config": {"id": "crew", "members": [{"type": "agent", "agent_id": "coder"}]},
            },
        )

        assert response.status_code == 400
        assert "External agents cannot be team members: coder" in response.json()["detail"]

    def test_components_api_refuses_a_stored_external_step(self, db, components_client):
        ClaudeAgent(id="coder").save(db=db)

        response = components_client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {"steps": [{"type": "Step", "name": "code", "step_id": "code", "agent_id": "coder"}]},
            },
        )

        assert response.status_code == 400
        assert "External agents cannot be workflow steps: coder" in response.json()["detail"]

    def test_components_api_keeps_an_agents_kind(self, db, components_client):
        ClaudeAgent(id="coder").save(db=db)

        as_native = components_client.post("/components/coder/configs", json={"config": {"id": "coder"}})
        assert as_native.status_code == 400, as_native.text
        assert "would change what it loads as" in as_native.json()["detail"]

        as_codex = components_client.post("/components/coder/configs", json={"config": {"sdk": "codex", "id": "coder"}})
        assert as_codex.status_code == 400, as_codex.text

        same_kind = components_client.post(
            "/components/coder/configs", json={"config": {"sdk": "claude-agent-sdk", "id": "coder"}, "stage": "draft"}
        )
        assert same_kind.status_code == 201, same_kind.text
        draft_version = same_kind.json()["version"]

        edited = components_client.patch(
            f"/components/coder/configs/{draft_version}", json={"config": {"sdk": "codex", "id": "coder"}}
        )
        assert edited.status_code == 400, edited.text

        Agent(id="native", name="Native", db=db).save()
        as_external = components_client.post(
            "/components/native/configs", json={"config": {"sdk": "claude-agent-sdk", "id": "native"}}
        )
        assert as_external.status_code == 400, as_external.text

    def test_components_api_set_current_keeps_an_agents_kind(self, db, components_client):
        ClaudeAgent(id="coder").save(db=db)
        # A version of the other kind can only exist through a direct db write; publishing it makes it live.
        db.upsert_config(component_id="coder", config={"id": "coder"}, stage="published")
        assert db.get_component("coder")["current_version"] == 2

        rollback = components_client.post("/components/coder/configs/1/set-current")

        assert rollback.status_code == 400, rollback.text
        assert "cannot change kind" in rollback.json()["detail"]
        assert db.get_component("coder")["current_version"] == 2

    def test_components_api_stores_an_external_agent_config(self, db, components_client, registry):
        response = components_client.post(
            "/components",
            json={
                "name": "Coder",
                "component_id": "coder",
                "component_type": "agent",
                "config": {"sdk": "claude-agent-sdk", "id": "coder", "permission_mode": "plan"},
                "stage": "published",
            },
        )

        assert response.status_code == 201, response.text
        loaded = get_agent_by_id(db=db, id="coder", registry=registry, strict=True)
        assert isinstance(loaded, ClaudeAgent) and loaded.permission_mode == "plan"


class TestStudioRunner:
    """Stored external agents follow the code-registered ones in Studio: runnable, not buildable."""

    def test_dispatch_lookup_rebuilds_the_adapter(self, db, registry):
        from agno.tools.studio_runner import StudioRunnerTools

        ClaudeAgent(id="coder", permission_mode="plan").save(db=db)
        runner = StudioRunnerTools(db=db, registry=registry)

        found = runner._find_agent("coder", for_dispatch=True)

        assert isinstance(found, ClaudeAgent)
        assert found.permission_mode == "plan"
        assert found.db is db

    def test_non_dispatch_lookup_does_not_see_the_adapter(self, db, registry):
        from agno.tools.studio_runner import StudioRunnerTools

        ClaudeAgent(id="coder").save(db=db)
        runner = StudioRunnerTools(db=db, registry=registry)

        assert runner._find_agent("coder") is None

    def test_dispatch_needs_the_host_opt_in(self, db):
        from agno.tools.studio_runner import ComponentNotDispatchableError, StudioRunnerTools

        ClaudeAgent(id="coder").save(db=db)
        runner = StudioRunnerTools(db=db, registry=Registry(dbs=[db]))

        with pytest.raises(ComponentNotDispatchableError, match="allow_host_external_agents"):
            runner._find_agent("coder", for_dispatch=True)

    def test_dispatch_refuses_an_unresolvable_reference(self, db):
        from agno.tools.studio_runner import ComponentNeedsRegistryError, StudioRunnerTools

        ClaudeAgent(id="coder", sandbox=FakeSandbox(id="docker-local")).save(db=db)
        runner = StudioRunnerTools(db=db, registry=Registry(dbs=[db]))

        with pytest.raises(ComponentNeedsRegistryError, match="references sandbox 'docker-local'"):
            runner._find_agent("coder", for_dispatch=True)


# ---------------------------------------------------------------------------
# Registry sandboxes
# ---------------------------------------------------------------------------


class TestRegistrySandboxes:
    def test_add_and_get(self, agno_logs):
        registry = Registry()
        sandbox = FakeSandbox(id="docker-local")

        registry.add_sandbox(sandbox)
        registry.add_sandbox(sandbox)
        registry.add_sandbox(FakeSandbox())
        registry.add_sandbox(FakeSandbox(id="docker-local"))
        registry.add_sandbox("not a sandbox")

        assert registry.sandboxes == [sandbox]
        assert registry.get_sandbox("docker-local") is sandbox
        assert registry.get_sandbox("other") is None
        assert registry.get_sandbox_ids() == {"docker-local"}
        assert "multiple distinct sandboxes share id 'docker-local'" in agno_logs.text

    def test_agentos_walk_collects_sandboxes_from_external_agents(self):
        registry = Registry()
        sandbox = FakeSandbox(id="docker-local")
        unnamed = FakeSandbox()

        collect_components_from_os(
            [ClaudeAgent(id="coder", sandbox=sandbox), ClaudeAgent(id="other", sandbox=unnamed)], [], [], registry
        )

        assert registry.sandboxes == [sandbox]

    def test_agentos_walk_collects_external_agents_schema_and_db(self, db):
        registry = Registry()
        served = ClaudeAgent(id="coder", db=db, output_schema=Answer)

        collect_components_from_os([served], [], [], registry)

        assert registry.get_schema("Answer") is Answer
        assert registry.get_db(db.id) is db
        # Another stored agent naming the same schema and db now resolves them strictly.
        stored = ClaudeAgent(id="other", db=db, output_schema=Answer).to_dict()
        rebuilt = ClaudeAgent.from_dict(stored, registry=registry, strict=True)
        assert rebuilt.output_schema is Answer and rebuilt.db is db

    def test_agentos_registers_the_sandbox_of_a_served_external_agent(self):
        from agno.db.postgres import PostgresDb

        sandbox = FakeSandbox(id="docker-local")
        # A sandboxed agent needs Postgres; the engine connects lazily, so construction is enough.
        served = ClaudeAgent(
            id="coder", sandbox=sandbox, db=PostgresDb(db_url="postgresql+psycopg://ai:ai@127.0.0.1:1/none")
        )

        agent_os = AgentOS(id="test-os", agents=[served])

        assert agent_os.registry is not None
        assert agent_os.registry.get_sandbox("docker-local") is sandbox
        rebuilt = ClaudeAgent.from_dict(served.to_dict(), registry=agent_os.registry, strict=True)
        assert rebuilt.sandbox is sandbox

    def test_registry_route_lists_sandboxes(self):
        registry = Registry(sandboxes=[FakeSandbox(id="docker-local", env={"GITHUB_READ_TOKEN": "secret"})])
        app = FastAPI()
        app.include_router(get_registry_router(registry=registry, settings=AgnoAPISettings()))

        response = TestClient(app).get("/registry", params={"resource_type": "sandbox"})

        assert response.status_code == 200
        [entry] = response.json()["data"]
        assert entry["type"] == "sandbox"
        assert entry["id"] == "docker-local"
        assert entry["metadata"]["class_path"].endswith("FakeSandbox")
        assert "secret" not in response.text


# ---------------------------------------------------------------------------
# AgentOS serves stored external agents
# ---------------------------------------------------------------------------


class TestAgentOS:
    def test_stored_external_agents_need_the_host_opt_in(self, db, echo_storable):
        EchoAgent(id="echo-stored", name="Echo").save(db=db)
        app = AgentOS(id="test-os", db=db, registry=Registry(dbs=[db])).get_app()
        client = TestClient(app, raise_server_exceptions=False)

        listed = client.get("/agents")
        assert listed.status_code == 200, listed.text
        assert [agent["id"] for agent in listed.json()] == ["echo-stored"]

        detail = client.get("/agents/echo-stored")
        assert detail.status_code == 422, detail.text
        assert "allow_host_external_agents" in detail.json()["detail"]
        run = client.post("/agents/echo-stored/runs", data={"message": "hi", "stream": "false"})
        assert run.status_code == 422, run.text

    def test_unresolvable_external_config_stays_listed(self, db, registry):
        db.upsert_component(component_id="typo", component_type=ComponentType.AGENT, name="Typo")
        db.upsert_config(component_id="typo", config={"sdk": "claude-agent-sdkk", "id": "typo"}, stage="published")
        app = AgentOS(id="test-os", db=db, registry=registry).get_app()
        client = TestClient(app, raise_server_exceptions=False)

        listed = client.get("/agents")
        assert listed.status_code == 200, listed.text
        [entry] = listed.json()
        assert entry["id"] == "typo" and entry["metadata"]["sdk"] == "claude-agent-sdkk"

        run = client.post("/agents/typo/runs", data={"message": "hi", "stream": "false"})
        assert run.status_code == 422, run.text
        assert "claude-agent-sdkk" in run.json()["detail"]

    @pytest.fixture
    def client(self, db, registry, echo_storable) -> TestClient:
        ClaudeAgent(id="coder", name="Coder", description="Writes code", permission_mode="plan").save(db=db)
        EchoAgent(id="echo-stored", name="Echo", greeting="stored").save(db=db)
        app = AgentOS(id="test-os", db=db, registry=registry, agents=[EchoAgent(id="echo-code", name="Code")]).get_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_listing_shows_stored_external_agents(self, client):
        response = client.get("/agents")

        assert response.status_code == 200, response.text
        by_id = {agent["id"]: agent for agent in response.json()}
        assert by_id["echo-code"]["metadata"]["sdk"] == "echo"
        assert not by_id["echo-code"].get("is_component")
        assert by_id["coder"]["metadata"]["sdk"] == "claude-agent-sdk"
        assert by_id["coder"]["is_component"] is True
        assert by_id["coder"]["current_version"] == 1
        assert by_id["coder"]["stage"] == "published"
        assert by_id["coder"]["description"] == "Writes code"

    def test_detail_resolves_a_stored_external_agent(self, client):
        response = client.get("/agents/coder")

        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Coder"
        assert response.json()["metadata"]["sdk"] == "claude-agent-sdk"

    def test_run_executes_a_stored_external_agent(self, client, db):
        response = client.post(
            "/agents/echo-stored/runs", data={"message": "hi", "session_id": "s1", "stream": "false"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["content"] == "stored: hi"
        assert db.get_runs(session_id="s1")[0].agent_id == "echo-stored"

    def test_pinned_version_is_stamped_on_a_stored_external_agent_run(self, client, db):
        response = client.post(
            "/agents/echo-stored/runs",
            data={"message": "hi", "session_id": "s3", "stream": "false", "version": "1"},
        )

        assert response.status_code == 200, response.text
        # The continue route reloads the version recorded on the run, so the stamp must survive.
        [run] = db.get_runs(session_id="s3")
        assert run.metadata["agno_component_version"] == 1

    def test_streamed_run_of_a_stored_external_agent_persists_events(self, client, db):
        response = client.post("/agents/echo-stored/runs", data={"message": "hi", "session_id": "s2", "stream": "true"})

        assert response.status_code == 200, response.text
        # AgentOS turns store_events on for registered adapters; a stored one gets the same.
        [run] = db.get_runs(session_id="s2")
        assert run.events, "a stored external agent served by AgentOS keeps its run events"
