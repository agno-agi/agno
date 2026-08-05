"""Unit tests for StudioRunnerTools -- and StudioTools' embedding of it.

Uses a real SqliteDb backed by a pytest tmp_path so component persistence and
slug resolution run against the full storage path, not mocks. Run execution is
exercised through stub components that capture the identity kwargs the runner
threads through.
"""

import json
from typing import Any, Dict, Optional

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import StudioRunnerTools

# ----------------------------------------------------------------------
# Fixtures and stubs
# ----------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="runner-test-db", db_file=str(tmp_path / "runner.db"))


@pytest.fixture
def registry(db):
    return Registry(
        name="Runner Test Registry",
        models=[OpenAIResponses(id="gpt-5.4")],
        dbs=[db],
    )


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


def _context(user_id: Optional[str] = "ash", session_id: str = "caller-sess") -> RunContext:
    return RunContext(run_id="caller-run", session_id=session_id, user_id=user_id)


class _StubRunOutput:
    run_id = "run-1"
    session_id = "sub-sess-1"
    status = RunStatus.completed
    content = "done"


class _StubRequirement:
    def to_dict(self) -> Dict[str, Any]:
        return {"id": "req-1", "confirmation": None}


class _PausedRunOutput:
    run_id = "run-p"
    session_id = "sub-sess-p"
    status = RunStatus.paused
    content = None
    is_paused = True
    active_requirements = [_StubRequirement()]


class _StubAgent:
    id = "stub"
    name = "Stub"

    def __init__(self, output: Any = None):
        self._output = output or _StubRunOutput()
        self.seen: Optional[Dict[str, Any]] = None

    def run(self, message, user_id=None, session_id=None):
        self.seen = {"message": message, "user_id": user_id, "session_id": session_id}
        return self._output

    async def arun(self, message, user_id=None, session_id=None):
        self.seen = {"message": message, "user_id": user_id, "session_id": session_id}
        return self._output


class _StubTeam:
    id = "stub-team"
    name = "Stub Team"

    def __init__(self):
        self.seen: Optional[Dict[str, Any]] = None

    def run(self, message, user_id=None, session_id=None):
        self.seen = {"message": message, "user_id": user_id, "session_id": session_id}
        return _StubRunOutput()

    async def arun(self, message, user_id=None, session_id=None):
        self.seen = {"message": message, "user_id": user_id, "session_id": session_id}
        return _StubRunOutput()


class _StubWorkflow:
    id = "stub-wf"
    name = "Stub Workflow"

    def __init__(self):
        self.seen: Optional[Dict[str, Any]] = None

    def run(self, input=None, user_id=None, session_id=None):
        self.seen = {"input": input, "user_id": user_id, "session_id": session_id}
        return _StubRunOutput()

    async def arun(self, input=None, user_id=None, session_id=None):
        self.seen = {"input": input, "user_id": user_id, "session_id": session_id}
        return _StubRunOutput()


# ----------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------


class TestRegistration:
    def test_default_surface_is_discovery_plus_run(self, db):
        runner = StudioRunnerTools(db=db)
        expected = {"list_agents", "run_agent", "list_teams", "run_team", "list_workflows", "run_workflow"}
        assert expected == set(runner.functions.keys())
        assert expected == set(runner.async_functions.keys())

    def test_flags_scope_the_surface(self, db):
        runner = StudioRunnerTools(db=db, teams=False, workflows=False)
        assert {"list_agents", "run_agent"} == set(runner.functions.keys())
        assert {"list_agents", "run_agent"} == set(runner.async_functions.keys())

    def test_toolkit_name_is_overridable(self, db):
        assert StudioRunnerTools(db=db).name == "studio_runners"
        assert StudioRunnerTools(db=db, name="agent_runner").name == "agent_runner"

    def test_db_defaults_from_registry(self, registry, db):
        runner = StudioRunnerTools(registry=registry)
        assert runner.db is db

    def test_run_context_is_not_in_the_model_schema(self, db):
        runner = StudioRunnerTools(db=db)
        for functions in (runner.functions, runner.async_functions):
            function = functions["run_agent"]
            function.process_entrypoint()
            properties = (function.parameters or {}).get("properties") or {}
            assert set(properties) == {"agent_id", "message"}


# ----------------------------------------------------------------------
# Identity and session threading
# ----------------------------------------------------------------------


class TestIdentityThreading:
    def test_run_agent_threads_user_and_derived_session(self, db):
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("stub", "hi", run_context=_context()))
        assert stub.seen == {"message": "hi", "user_id": "ash", "session_id": "caller-sess--stub"}
        assert out == {
            "agent_id": "stub",
            "run_id": "run-1",
            "session_id": "sub-sess-1",
            "status": "COMPLETED",
            "content": "done",
        }

    def test_run_agent_without_context_keeps_component_defaults(self, db):
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("stub", "hi"))
        assert stub.seen == {"message": "hi", "user_id": None, "session_id": None}
        assert out["status"] == "COMPLETED"

    def test_run_agent_resolves_code_defined_by_name(self, db):
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("Stub", "hi", run_context=_context()))
        assert "error" not in out
        # The payload and the derived session both carry the component's real id.
        assert out["agent_id"] == "stub"
        assert stub.seen is not None and stub.seen["session_id"] == "caller-sess--stub"

    def test_run_team_threads_identity(self, db):
        stub = _StubTeam()
        runner = StudioRunnerTools(db=db, teams_list=[stub])
        out = _loads(runner.run_team("stub-team", "hi", run_context=_context()))
        assert stub.seen == {"message": "hi", "user_id": "ash", "session_id": "caller-sess--stub-team"}
        assert out["team_id"] == "stub-team"

    def test_run_workflow_threads_identity(self, db):
        stub = _StubWorkflow()
        runner = StudioRunnerTools(db=db, workflows_list=[stub])
        out = _loads(runner.run_workflow("stub-wf", "go", run_context=_context()))
        assert stub.seen == {"input": "go", "user_id": "ash", "session_id": "caller-sess--stub-wf"}
        assert out["workflow_id"] == "stub-wf"

    @pytest.mark.asyncio
    async def test_arun_agent_threads_identity(self, db):
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(await runner.arun_agent("stub", "hi", run_context=_context()))
        assert stub.seen == {"message": "hi", "user_id": "ash", "session_id": "caller-sess--stub"}
        assert out["status"] == "COMPLETED"


# ----------------------------------------------------------------------
# Paused runs
# ----------------------------------------------------------------------


class TestPausedRuns:
    def test_paused_run_returns_requirements_and_resume_ids(self, db):
        stub = _StubAgent(output=_PausedRunOutput())
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("stub", "hi", run_context=_context()))
        assert out["status"] == "PAUSED"
        assert out["run_id"] == "run-p"
        assert out["session_id"] == "sub-sess-p"
        assert out["requirements"] == [{"id": "req-1", "confirmation": None}]

    def test_completed_run_carries_no_requirements_key(self, db):
        runner = StudioRunnerTools(db=db, agents_list=[_StubAgent()])
        out = _loads(runner.run_agent("stub", "hi"))
        assert "requirements" not in out
        assert "media" not in out

    def test_media_bearing_run_reports_counts(self, db):
        output = _StubRunOutput()
        output.images = [object(), object()]  # type: ignore[attr-defined]
        runner = StudioRunnerTools(db=db, agents_list=[_StubAgent(output=output)])
        out = _loads(runner.run_agent("stub", "hi"))
        assert out["media"] == {"images": 2}

    @pytest.mark.asyncio
    async def test_async_paused_run_returns_requirements(self, db):
        stub = _StubAgent(output=_PausedRunOutput())
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(await runner.arun_agent("stub", "hi"))
        assert out["status"] == "PAUSED"
        assert out["requirements"] == [{"id": "req-1", "confirmation": None}]


# ----------------------------------------------------------------------
# Resolution: DB components, slug fallback
# ----------------------------------------------------------------------


class TestResolution:
    def test_find_agent_resolves_db_component_by_display_name(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        created = _loads(studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4"))
        assert created["id"] == "radar-scout"

        runner = StudioRunnerTools(registry=registry, db=db)
        by_id = runner._find_agent("radar-scout")
        by_name = runner._find_agent("Radar Scout")
        assert by_id is not None and by_id.id == "radar-scout"
        assert by_name is not None and by_name.id == "radar-scout"

    def test_run_agent_not_found(self, db):
        runner = StudioRunnerTools(db=db)
        out = _loads(runner.run_agent("nope", "hi"))
        assert out == {"error": "Agent not found: nope"}

    def test_run_agent_rejects_team_id(self, registry, db):
        studio = StudioTools(registry=registry, db=db, teams=True)
        studio.create_agent(name="member", instructions="i", model_id="gpt-5.4")
        studio.create_team(name="squad", instructions="i", member_ids=["member"], model_id="gpt-5.4")

        runner = StudioRunnerTools(registry=registry, db=db)
        out = _loads(runner.run_agent("squad", "hi"))
        assert "error" in out


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


class TestDiscovery:
    def test_list_agents_shows_db_components_only(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar", instructions="i", model_id="gpt-5.4", description="scans the week")

        runner = StudioRunnerTools(registry=registry, db=db, agents_list=[_StubAgent()])
        out = _loads(runner.list_agents())
        assert out["count"] == 1 and out["total"] == 1
        assert out["agents"] == [{"id": "radar", "name": "Radar", "description": "scans the week"}]

    def test_list_agents_reports_total_beyond_cap(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        for name in ("one", "two", "three"):
            studio.create_agent(name=name, instructions="i", model_id="gpt-5.4")

        runner = StudioRunnerTools(registry=registry, db=db, list_limit=2)
        out = _loads(runner.list_agents())
        assert out["count"] == 2
        assert out["total"] == 3

    def test_list_without_db_errors(self):
        runner = StudioRunnerTools()
        out = _loads(runner.list_agents())
        assert "error" in out


# ----------------------------------------------------------------------
# StudioTools embedding
# ----------------------------------------------------------------------


class TestStudioEmbedding:
    def test_studio_registers_runner_bound_methods(self, registry, db):
        studio = StudioTools(registry=registry, db=db, teams=True, workflows=True)
        for name in ("run_agent", "run_team", "run_workflow"):
            entrypoint = studio.functions[name].entrypoint
            assert getattr(entrypoint, "__self__", None) is studio._runner_tools
            async_entrypoint = studio.async_functions[name].entrypoint
            assert getattr(async_entrypoint, "__self__", None) is studio._runner_tools

    def test_identity_threads_through_studio_registered_tool(self, registry, db):
        stub = _StubAgent()
        studio = StudioTools(registry=registry, db=db, agents_list=[stub])
        out = _loads(studio.functions["run_agent"].entrypoint("stub", "hi", run_context=_context()))
        assert stub.seen == {"message": "hi", "user_id": "ash", "session_id": "caller-sess--stub"}
        assert out["agent_id"] == "stub"

    def test_studio_lookups_gain_slug_resolution(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        # get_agent by display name resolves via the shared runner lookup path.
        out = _loads(studio.get_agent("Radar Scout"))
        assert out.get("id") == "radar-scout"
