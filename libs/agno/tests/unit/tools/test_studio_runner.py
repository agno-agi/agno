"""Unit tests for StudioRunnerTools -- and StudioTools' embedding of it.

Uses a real SqliteDb backed by a pytest tmp_path so component persistence and
name/slug resolution run against the full storage path, not mocks. Run
execution is exercised through stub components that capture the identity and
stream kwargs the runner threads through.
"""

import json
from typing import Any, Dict, Optional

import pytest
from pydantic import BaseModel

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.tools.function import FunctionCall
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


class _StructuredContent(BaseModel):
    title: str
    n: int


class _StructuredRunOutput:
    run_id = "run-s"
    session_id = "sub-sess-s"
    status = RunStatus.completed
    content = _StructuredContent(title="Q3", n=3)

    def get_content_as_string(self, **kwargs) -> str:
        return self.content.model_dump_json(exclude_none=True, **kwargs)


class _StubAgent:
    id = "stub"
    name = "Stub"

    def __init__(self, output: Any = None):
        self._output = output or _StubRunOutput()
        self.seen: Optional[Dict[str, Any]] = None
        self.copied = False

    def run(self, message, stream=None, user_id=None, session_id=None):
        self.seen = {"message": message, "stream": stream, "user_id": user_id, "session_id": session_id}
        return self._output

    async def arun(self, message, stream=None, user_id=None, session_id=None):
        self.seen = {"message": message, "stream": stream, "user_id": user_id, "session_id": session_id}
        return self._output

    def deep_copy(self):
        # A distinct instance that shares state, so tests can see both the
        # copy call and the run through the original stub.
        self.copied = True
        clone = object.__new__(type(self))
        clone.__dict__ = self.__dict__
        return clone


class _StubTeam:
    id = "stub-team"
    name = "Stub Team"

    def __init__(self):
        self.seen: Optional[Dict[str, Any]] = None
        self.copied = False

    def run(self, message, stream=None, user_id=None, session_id=None):
        self.seen = {"message": message, "stream": stream, "user_id": user_id, "session_id": session_id}
        return _StubRunOutput()

    async def arun(self, message, stream=None, user_id=None, session_id=None):
        self.seen = {"message": message, "stream": stream, "user_id": user_id, "session_id": session_id}
        return _StubRunOutput()

    def deep_copy(self):
        # A distinct instance that shares state, so tests can see both the
        # copy call and the run through the original stub.
        self.copied = True
        clone = object.__new__(type(self))
        clone.__dict__ = self.__dict__
        return clone


class _StubWorkflow:
    id = "stub-wf"
    name = "Stub Workflow"

    def __init__(self):
        self.seen: Optional[Dict[str, Any]] = None
        self.copied = False

    def run(self, input=None, stream=None, user_id=None, session_id=None):
        self.seen = {"input": input, "stream": stream, "user_id": user_id, "session_id": session_id}
        return _StubRunOutput()

    async def arun(self, input=None, stream=None, user_id=None, session_id=None):
        self.seen = {"input": input, "stream": stream, "user_id": user_id, "session_id": session_id}
        return _StubRunOutput()

    def deep_copy(self):
        # A distinct instance that shares state, so tests can see both the
        # copy call and the run through the original stub.
        self.copied = True
        clone = object.__new__(type(self))
        clone.__dict__ = self.__dict__
        return clone


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
        out = _loads(runner.run_agent("stub", "hi", _agno_run_context=_context()))
        assert stub.seen == {
            "message": "hi",
            "stream": False,
            "user_id": "ash",
            "session_id": "caller-sess--agent--stub",
        }
        assert out == {
            "agent_id": "stub",
            "run_id": "run-1",
            "session_id": "sub-sess-1",
            "status": "COMPLETED",
            "content": "done",
        }

    def test_sessionless_run_gets_a_fresh_session_per_call(self, db):
        # Forwarding session_id=None would collapse every sessionless caller
        # into the target's sticky per-instance session; the REST and MCP run
        # planes mint a fresh session the same way.
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("stub", "hi"))
        assert stub.seen is not None and stub.seen["user_id"] is None
        first_session = stub.seen["session_id"]
        runner.run_agent("stub", "hi")
        assert stub.seen is not None
        second_session = stub.seen["session_id"]
        assert first_session and second_session and first_session != second_session
        assert out["status"] == "COMPLETED"

    def test_run_agent_resolves_code_defined_by_name(self, db):
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("Stub", "hi", _agno_run_context=_context()))
        assert "error" not in out
        # The payload and the derived session both carry the component's real id.
        assert out["agent_id"] == "stub"
        assert stub.seen is not None and stub.seen["session_id"] == "caller-sess--agent--stub"

    def test_run_team_threads_identity(self, db):
        stub = _StubTeam()
        runner = StudioRunnerTools(db=db, teams_list=[stub])
        out = _loads(runner.run_team("stub-team", "hi", _agno_run_context=_context()))
        assert stub.seen == {
            "message": "hi",
            "stream": False,
            "user_id": "ash",
            "session_id": "caller-sess--team--stub-team",
        }
        assert out["team_id"] == "stub-team"

    def test_run_workflow_threads_identity(self, db):
        stub = _StubWorkflow()
        runner = StudioRunnerTools(db=db, workflows_list=[stub])
        out = _loads(runner.run_workflow("stub-wf", "go", _agno_run_context=_context()))
        assert stub.seen == {
            "input": "go",
            "stream": False,
            "user_id": "ash",
            "session_id": "caller-sess--workflow--stub-wf",
        }
        assert out["workflow_id"] == "stub-wf"

    @pytest.mark.asyncio
    async def test_arun_agent_threads_identity(self, db):
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(await runner.arun_agent("stub", "hi", _agno_run_context=_context()))
        assert stub.seen == {
            "message": "hi",
            "stream": False,
            "user_id": "ash",
            "session_id": "caller-sess--agent--stub",
        }
        assert out["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_arun_team_and_workflow_pin_stream_off(self, db):
        team = _StubTeam()
        wf = _StubWorkflow()
        runner = StudioRunnerTools(db=db, teams_list=[team], workflows_list=[wf])
        await runner.arun_team("stub-team", "hi")
        await runner.arun_workflow("stub-wf", "go")
        assert team.seen is not None and team.seen["stream"] is False
        assert wf.seen is not None and wf.seen["stream"] is False


# ----------------------------------------------------------------------
# Paused runs
# ----------------------------------------------------------------------


class TestPausedRuns:
    def test_paused_run_returns_requirements_and_resume_ids(self, db):
        stub = _StubAgent(output=_PausedRunOutput())
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("stub", "hi", _agno_run_context=_context()))
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

    def test_file_artifacts_are_counted(self, db):
        # RunOutput carries produced file artifacts on `files`; they must be counted too.
        output = _StubRunOutput()
        output.files = [object(), object(), object()]  # type: ignore[attr-defined]
        runner = StudioRunnerTools(db=db, agents_list=[_StubAgent(output=output)])
        out = _loads(runner.run_agent("stub", "hi"))
        assert out["media"] == {"files": 3}

    def test_structured_content_serializes_as_json_not_repr(self, db):
        runner = StudioRunnerTools(db=db, agents_list=[_StubAgent(output=_StructuredRunOutput())])
        out = _loads(runner.run_agent("stub", "hi"))
        assert json.loads(out["content"]) == {"title": "Q3", "n": 3}

    @pytest.mark.asyncio
    async def test_async_paused_run_returns_requirements(self, db):
        stub = _StubAgent(output=_PausedRunOutput())
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(await runner.arun_agent("stub", "hi"))
        assert out["status"] == "PAUSED"
        assert out["requirements"] == [{"id": "req-1", "confirmation": None}]


# ----------------------------------------------------------------------
# Injected identity cannot be overridden by tool-call arguments
# ----------------------------------------------------------------------


def _passthrough_hook(function_name, function_call, arguments):
    return function_call(**arguments)


async def _async_passthrough_hook(function_name, function_call, arguments):
    return await function_call(**arguments)


class TestInjectionGuard:
    def _registered_run_agent(self, db, stub, tool_hooks=None):
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        function = runner.functions["run_agent"]
        function.process_entrypoint()
        function.tool_hooks = tool_hooks
        function._run_context = _context()
        return function

    def test_spoofed_context_is_dropped_on_the_hooks_path(self, db):
        # The tool-hooks execution chain merges tool-call arguments over the
        # injected ones; a model-emitted _agno_run_context must not win.
        stub = _StubAgent()
        function = self._registered_run_agent(db, stub, tool_hooks=[_passthrough_hook])
        call = FunctionCall(
            function=function,
            arguments={
                "agent_id": "stub",
                "message": "hi",
                "_agno_run_context": {"run_id": "x", "user_id": "victim", "session_id": "victim-sess"},
            },
        )
        result = call.execute()
        assert result.status == "success"
        assert stub.seen is not None
        assert stub.seen["user_id"] == "ash"
        assert stub.seen["session_id"] == "caller-sess--agent--stub"

    def test_spoofed_context_is_dropped_without_hooks(self, db):
        stub = _StubAgent()
        function = self._registered_run_agent(db, stub)
        call = FunctionCall(
            function=function,
            arguments={"agent_id": "stub", "message": "hi", "_agno_run_context": None},
        )
        result = call.execute()
        assert result.status == "success"
        assert stub.seen is not None
        assert stub.seen["user_id"] == "ash"

    @pytest.mark.asyncio
    async def test_spoofed_context_is_dropped_on_the_async_hooks_path(self, db):
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        function = runner.async_functions["run_agent"]
        function.process_entrypoint()
        function.tool_hooks = [_async_passthrough_hook]
        function._run_context = _context()
        call = FunctionCall(
            function=function,
            arguments={"agent_id": "stub", "message": "hi", "_agno_run_context": None},
        )
        result = await call.aexecute()
        assert result.status == "success"
        assert stub.seen is not None
        assert stub.seen["user_id"] == "ash"

    def test_schema_visible_param_named_like_an_injected_one_keeps_the_model_value(self):
        # A tool whose schema declares a non-identity injected name -- a wrapper exposing
        # the wrapped tool's own "files" argument -- keeps the model-supplied value.
        from agno.tools.function import Function

        received: Dict[str, Any] = {}

        def upload(files: str, note: str) -> str:
            received.update({"files": files, "note": note})
            return "ok"

        for hooks in ([_passthrough_hook], None):
            received.clear()
            function = Function(
                name="upload",
                entrypoint=upload,
                parameters={
                    "type": "object",
                    "properties": {"files": {"type": "string"}, "note": {"type": "string"}},
                    "required": ["files", "note"],
                },
            )
            function.process_entrypoint()
            assert "files" in (function.parameters or {}).get("properties", {})
            function.tool_hooks = hooks
            call = FunctionCall(function=function, arguments={"files": "a.pdf", "note": "n"})
            result = call.execute()
            assert result.status == "success"
            assert received == {"files": "a.pdf", "note": "n"}


# ----------------------------------------------------------------------
# Resolution: exact ids, display names, ambiguity, slug fallback
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

    def test_exact_id_beats_code_defined_display_name(self, db):
        shadow = _StubAgent()
        shadow.id = "triage-v2"
        shadow.name = "researcher"
        target = _StubAgent()
        target.id = "researcher"
        target.name = "Researcher"
        runner = StudioRunnerTools(db=db, agents_list=[shadow, target])
        assert runner._find_agent("researcher") is target

    def test_db_exact_id_beats_code_defined_display_name(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="radar", instructions="i", model_id="gpt-5.4")
        shadow = _StubAgent()
        shadow.id = "other"
        shadow.name = "radar"
        runner = StudioRunnerTools(registry=registry, db=db, agents_list=[shadow])
        found = runner._find_agent("radar")
        assert found is not shadow
        assert getattr(found, "id", None) == "radar"

    def test_display_name_resolves_across_type_slug_collision(self, registry, db):
        # The team owns the base slug; the same-named agent got a -2 suffix.
        # Name resolution is typed, so each type's lookup reaches its own component.
        studio = StudioTools(registry=registry, db=db, teams=True)
        studio.create_agent(name="member", instructions="i", model_id="gpt-5.4")
        studio.create_team(name="Radar Scout", instructions="i", member_ids=["member"], model_id="gpt-5.4")
        created = _loads(studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4"))
        assert created["id"] == "radar-scout-2"

        runner = StudioRunnerTools(registry=registry, db=db)
        agent = runner._find_agent("Radar Scout")
        team = runner._find_team("Radar Scout")
        assert agent is not None and agent.id == "radar-scout-2"
        assert team is not None and team.id == "radar-scout"

    def test_ambiguous_display_name_errors_with_matching_ids(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")

        runner = StudioRunnerTools(registry=registry, db=db)
        out = _loads(runner.run_agent("Radar Scout", "hi"))
        assert "Ambiguous" in out["error"]
        assert "radar-scout" in out["error"] and "radar-scout-2" in out["error"]
        # Exact ids stay unambiguous.
        found = runner._find_agent("radar-scout-2")
        assert found is not None and found.id == "radar-scout-2"

    @pytest.mark.asyncio
    async def test_async_ambiguous_display_name_errors(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")

        runner = StudioRunnerTools(registry=registry, db=db)
        out = _loads(await runner.arun_agent("Radar Scout", "hi"))
        assert "Ambiguous" in out["error"]

    def test_slug_fallback_resolves_when_name_lookup_misses(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")

        runner = StudioRunnerTools(registry=registry, db=db)
        found = runner._find_agent("radar scout!")
        assert found is not None and found.id == "radar-scout"

    def test_name_lookup_pages_beyond_first_page(self, registry, db, monkeypatch):
        import agno.tools.studio_runner as studio_runner_module

        monkeypatch.setattr(studio_runner_module, "_NAME_LOOKUP_PAGE", 1)
        studio = StudioTools(registry=registry, db=db)
        for name in ("Oldest Match", "newer-a", "newer-b"):
            studio.create_agent(name=name, instructions="i", model_id="gpt-5.4")

        runner = StudioRunnerTools(registry=registry, db=db)
        found = runner._find_agent("Oldest Match")
        assert found is not None and found.id == "oldest-match"

    def test_duplicate_code_defined_names_error(self, db):
        twin_a = _StubAgent()
        twin_a.id = "twin-a"
        twin_a.name = "Twin"
        twin_b = _StubAgent()
        twin_b.id = "twin-b"
        twin_b.name = "Twin"
        runner = StudioRunnerTools(db=db, agents_list=[twin_a, twin_b])
        out = _loads(runner.run_agent("Twin", "hi"))
        assert "Ambiguous" in out["error"]
        assert "twin-a" in out["error"] and "twin-b" in out["error"]

    def test_broken_exact_id_is_not_reinterpreted_as_a_name(self, registry, db, monkeypatch):
        # Agent "reports" exists but its config no longer loads; a different
        # agent is *named* "reports". The exact id must report not-found, not
        # silently dispatch the name match.
        from agno.agent.agent import Agent as AgentClass

        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Reports", instructions="i", model_id="gpt-5.4")
        created = _loads(studio.create_agent(name="reports", instructions="i", model_id="gpt-5.4"))
        assert created["id"] == "reports-2"

        original_from_dict = AgentClass.from_dict

        def guarded(config, **kwargs):
            if isinstance(config, dict) and config.get("name") == "Reports":
                raise RuntimeError("broken config")
            return original_from_dict(config, **kwargs)

        monkeypatch.setattr(AgentClass, "from_dict", staticmethod(guarded))

        runner = StudioRunnerTools(registry=registry, db=db)
        out = _loads(runner.run_agent("reports", "hi"))
        assert out == {"error": "Agent not found: reports"}

    def test_works_on_db_without_component_support(self):
        # In-memory and most non-SQL adapters do not implement component
        # storage; code-defined dispatch must still work and misses must stay
        # JSON errors, never raw NotImplementedError.
        from agno.db.in_memory import InMemoryDb

        stub = _StubAgent()
        runner = StudioRunnerTools(db=InMemoryDb(), agents_list=[stub])
        out = _loads(runner.run_agent("Stub", "hi"))
        assert out["agent_id"] == "stub"
        missing = _loads(runner.run_agent("nope", "hi"))
        assert missing == {"error": "Agent not found: nope"}

    def test_db_failure_during_resolution_returns_error_payload(self, db):
        runner = StudioRunnerTools(db=db)

        def boom(*args, **kwargs):
            raise RuntimeError("connection reset")

        runner.db.list_components = boom  # type: ignore[method-assign]
        out = _loads(runner.run_agent("Some Name", "hi"))
        assert "connection reset" in out["error"]


# ----------------------------------------------------------------------
# Dispatch isolation: fresh copies, per-type sessions, preserved dbs
# ----------------------------------------------------------------------


class TestDispatchIsolation:
    def test_code_defined_targets_are_deep_copied_per_run(self, db):
        stub = _StubAgent()
        team = _StubTeam()
        wf = _StubWorkflow()
        runner = StudioRunnerTools(db=db, agents_list=[stub], teams_list=[team], workflows_list=[wf])
        runner.run_agent("stub", "hi")
        runner.run_team("stub-team", "hi")
        runner.run_workflow("stub-wf", "go")
        assert stub.copied and team.copied and wf.copied

    def test_agent_and_team_sharing_an_id_get_separate_sessions(self, db):
        agent = _StubAgent()
        agent.id = "shared"
        agent.name = "Shared Agent"
        team = _StubTeam()
        team.id = "shared"
        team.name = "Shared Team"
        runner = StudioRunnerTools(db=db, agents_list=[agent], teams_list=[team])
        runner.run_agent("shared", "hi", _agno_run_context=_context())
        runner.run_team("shared", "hi", _agno_run_context=_context())
        assert agent.seen is not None and team.seen is not None
        assert agent.seen["session_id"] == "caller-sess--agent--shared"
        assert team.seen["session_id"] == "caller-sess--team--shared"

    def test_bad_deep_copy_refuses_dispatch(self, db):
        # deep_copy rebuilds via __init__ and can blank a subclass or raise.
        # The runner must not dispatch the bad copy. It must also not fall
        # back to the shared instance. It must return an error.
        class _LossyCopyAgent(_StubAgent):
            def deep_copy(self):
                blank = _StubAgent()
                blank.id = None
                blank.name = None
                return blank

        class _RaisingCopyAgent(_StubAgent):
            def deep_copy(self):
                raise TypeError("missing 1 required positional argument")

        class _NoCopyAgent(_StubAgent):
            deep_copy = None

        lossy = _LossyCopyAgent()
        runner = StudioRunnerTools(db=db, agents_list=[lossy])
        out = _loads(runner.run_agent("stub", "hi"))
        assert "lost its identity" in out["error"]
        assert lossy.seen is None

        raising = _RaisingCopyAgent()
        runner = StudioRunnerTools(db=db, agents_list=[raising])
        out = _loads(runner.run_agent("stub", "hi"))
        assert "deep_copy failed" in out["error"]
        assert raising.seen is None

        runner = StudioRunnerTools(db=db, agents_list=[_NoCopyAgent()])
        out = _loads(runner.run_agent("stub", "hi"))
        assert "has no deep_copy" in out["error"]

    def test_loader_keeps_config_declared_db(self, registry, db, tmp_path, monkeypatch):
        # A db reconstructed from the component's own config (possibly carrying
        # table overrides) must not be overwritten by the catalog db.
        from agno.agent.agent import Agent as AgentClass

        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar", instructions="i", model_id="gpt-5.4")

        own_db = SqliteDb(id="component-own-db", db_file=str(tmp_path / "own.db"))
        original_from_dict = AgentClass.from_dict

        def with_own_db(config, **kwargs):
            agent = original_from_dict(config, **kwargs)
            agent.db = own_db
            return agent

        monkeypatch.setattr(AgentClass, "from_dict", staticmethod(with_own_db))
        runner = StudioRunnerTools(registry=registry, db=db)
        found = runner._find_agent("radar")
        assert found is not None
        assert found.db is own_db


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

    def test_list_on_db_without_component_support_returns_empty_not_error(self):
        # A db adapter that does not implement component storage must degrade to an empty
        # listing, not surface an argument-less NotImplementedError as {"error": ""}.
        from agno.db.in_memory import InMemoryDb

        runner = StudioRunnerTools(db=InMemoryDb())
        out = _loads(runner.list_agents())
        assert out == {"agents": [], "count": 0, "total": 0}


# ----------------------------------------------------------------------
# StudioTools embedding
# ----------------------------------------------------------------------


class TestStudioEmbedding:
    def test_public_run_methods_forward_to_the_runner(self, registry, db):
        stub = _StubAgent()
        studio = StudioTools(registry=registry, db=db, agents_list=[stub])
        for name in ("run_agent", "run_team", "run_workflow", "arun_agent", "arun_team", "arun_workflow"):
            assert hasattr(studio, name)
        out = _loads(studio.run_agent("stub", "hi"))
        assert out["agent_id"] == "stub"
        assert stub.seen is not None

    @pytest.mark.asyncio
    async def test_public_arun_agent_forwards_to_the_runner(self, registry, db):
        stub = _StubAgent()
        studio = StudioTools(registry=registry, db=db, agents_list=[stub])
        out = _loads(await studio.arun_agent("stub", "hi"))
        assert out["agent_id"] == "stub"

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
        out = _loads(studio.functions["run_agent"].entrypoint("stub", "hi", _agno_run_context=_context()))
        assert stub.seen == {
            "message": "hi",
            "stream": False,
            "user_id": "ash",
            "session_id": "caller-sess--agent--stub",
        }
        assert out["agent_id"] == "stub"

    def test_studio_lookups_gain_name_resolution(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        # get_agent by display name resolves via the shared runner lookup path.
        out = _loads(studio.get_agent("Radar Scout"))
        assert out.get("id") == "radar-scout"

    def test_get_agent_ambiguous_name_errors(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        out = _loads(studio.get_agent("Radar Scout"))
        assert "Ambiguous" in out.get("error", "")

    def test_edit_resolves_display_name_to_canonical_id(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        out = _loads(studio.edit_agent("Radar Scout", instructions="updated"))
        assert out.get("status") == "edited"
        assert out.get("id") == "radar-scout"
        fetched = _loads(studio.get_agent("radar-scout"))
        assert fetched["instructions"] == "updated"

    def test_exact_team_member_id_beats_agent_display_name(self, registry, db):
        studio = StudioTools(registry=registry, db=db, teams=True)
        studio.create_agent(name="member", instructions="i", model_id="gpt-5.4")
        studio.create_team(name="support", instructions="i", member_ids=["member"], model_id="gpt-5.4")
        # An agent NAMED "support" (stored as support-2) must not steal the
        # team's exact id in member resolution.
        created_agent = _loads(studio.create_agent(name="support", instructions="i", model_id="gpt-5.4"))
        assert created_agent["id"] == "support-2"

        created = _loads(studio.create_team(name="squad", instructions="i", member_ids=["support"], model_id="gpt-5.4"))
        assert created.get("member_ids") == ["support"]

    def test_list_shows_db_component_named_like_a_code_id(self, registry, db):
        code_agent = _StubAgent()
        code_agent.id = "support"
        code_agent.name = "Support Code"
        shadowed = StudioTools(registry=registry, db=db, agents_list=[code_agent])
        created = _loads(shadowed.create_agent(name="support", instructions="i", model_id="gpt-5.4"))
        assert created["id"] == "support-2"

        listed = _loads(shadowed.list_agents())
        ids = {row["id"] for row in listed["agents"]}
        assert "support" in ids
        assert "support-2" in ids

    def test_edit_collision_error_points_at_the_editable_component(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        shadow = _StubAgent()
        shadow.id = "code-1"
        shadow.name = "Radar Scout"
        shadowed = StudioTools(registry=registry, db=db, agents_list=[shadow])
        out = _loads(shadowed.edit_agent("Radar Scout", instructions="x"))
        assert "Cannot edit code-defined agent" in out["error"]
        assert "radar-scout" in out["error"]

    def test_cross_type_member_id_collision_errors(self, registry, db):
        # An agent and team may legally share an id (uniqueness is per type);
        # member resolution must refuse rather than silently pick the agent.
        studio = StudioTools(registry=registry, db=db, teams=True)
        studio.create_agent(name="helper", instructions="i", model_id="gpt-5.4")
        studio.create_team(name="shared", instructions="i", member_ids=["helper"], model_id="gpt-5.4")
        code_agent = _StubAgent()
        code_agent.id = "shared"
        code_agent.name = "Shared Agent"
        shadowed = StudioTools(registry=registry, db=db, teams=True, agents_list=[code_agent])
        out = _loads(shadowed.create_team(name="squad", instructions="i", member_ids=["shared"], model_id="gpt-5.4"))
        assert "matches both an agent and a team" in out.get("error", "")

    def test_cross_type_member_name_collision_errors(self, registry, db):
        studio = StudioTools(registry=registry, db=db, teams=True)
        studio.create_agent(name="Ops", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="helper", instructions="i", model_id="gpt-5.4")
        studio.create_team(name="Ops", instructions="i", member_ids=["helper"], model_id="gpt-5.4")
        out = _loads(studio.create_team(name="squad", instructions="i", member_ids=["Ops"], model_id="gpt-5.4"))
        assert "matches both an agent and a team" in out.get("error", "")

    def test_registry_less_runner_refuses_tool_bearing_component(self, db):
        from agno.tools.calculator import CalculatorTools

        armed_registry = Registry(
            name="Armed Registry",
            models=[OpenAIResponses(id="gpt-5.4")],
            tools=[CalculatorTools()],
            dbs=[db],
        )
        studio = StudioTools(registry=armed_registry, db=db)
        studio.create_agent(name="Armed", instructions="i", model_id="gpt-5.4", tool_names=["calculator"])
        runner = StudioRunnerTools(db=db)
        out = _loads(runner.run_agent("armed", "hi"))
        assert "registry" in out.get("error", "")
        # With the registry the same component resolves.
        with_registry = StudioRunnerTools(registry=armed_registry, db=db)
        assert with_registry._find_agent("armed") is not None

    def test_registry_less_runner_refuses_team_with_tool_bearing_member(self, db):
        from agno.tools.calculator import CalculatorTools

        armed_registry = Registry(
            name="Armed Registry",
            models=[OpenAIResponses(id="gpt-5.4")],
            tools=[CalculatorTools()],
            dbs=[db],
        )
        studio = StudioTools(registry=armed_registry, db=db, teams=True)
        studio.create_agent(name="Armed", instructions="i", model_id="gpt-5.4", tool_names=["calculator"])
        studio.create_team(name="Crew", instructions="i", member_ids=["armed"], model_id="gpt-5.4")

        runner = StudioRunnerTools(db=db)
        out = _loads(runner.run_team("crew", "hi"))
        assert "registry" in out.get("error", "")

    def test_registry_less_runner_refuses_workflow_with_code_defined_step(self, registry, db):
        code_agent = _StubAgent()
        studio = StudioTools(registry=registry, db=db, workflows=True, agents_list=[code_agent])
        studio.create_workflow(name="Flow", description="d", step_specs=[{"name": "s1", "agent_id": "stub"}])

        runner = StudioRunnerTools(db=db)
        out = _loads(runner.run_workflow("flow", "go"))
        assert "registry" in out.get("error", "")
        assert "not found" not in out.get("error", "")

    def test_create_team_ambiguous_member_name_errors(self, registry, db):
        studio = StudioTools(registry=registry, db=db, teams=True)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        out = _loads(studio.create_team(name="squad", instructions="i", member_ids=["Radar Scout"], model_id="gpt-5.4"))
        assert "Ambiguous" in out.get("error", "")

    def test_delete_requires_exact_id_and_points_to_it(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4")
        out = _loads(studio.delete_agent("Radar Scout"))
        assert "error" in out
        assert "radar-scout" in out["error"]
        assert _loads(studio.delete_agent("radar-scout"))["status"] == "deleted"

    def test_edit_reaches_db_component_shadowed_by_code_defined_name(self, registry, db):
        # A code-defined component NAMED like a DB component's id must not make
        # the DB component uneditable: exact ids win on every path.
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="support", instructions="i", model_id="gpt-5.4")
        shadow = _StubAgent()
        shadow.id = "code-1"
        shadow.name = "support"
        shadowed = StudioTools(registry=registry, db=db, agents_list=[shadow])
        got = _loads(shadowed.get_agent("support"))
        assert got["id"] == "support"
        out = _loads(shadowed.edit_agent("support", instructions="updated"))
        assert out.get("status") == "edited"
        assert out.get("id") == "support"

    def test_edit_by_display_name_accumulates_drafts_with_versions(self, registry, db):
        # The edit base version must come from the RESOLVED id: a display-name
        # edit picks up the pending draft, not the published config.
        studio = StudioTools(registry=registry, db=db, versions=True)
        studio.create_agent(name="Radar Scout", instructions="original", model_id="gpt-5.4")
        first = _loads(studio.edit_agent("radar-scout", instructions="first-change"))
        assert first.get("status") == "edited"
        second = _loads(studio.edit_agent("Radar Scout", description="second-change"))
        assert second.get("status") == "edited"

        configs = db.list_configs("radar-scout", include_config=True)
        drafts = [c for c in configs if c.get("stage") == "draft"]
        latest = max(drafts, key=lambda c: c["version"])
        assert latest["config"]["instructions"] == "first-change"
        assert latest["config"]["description"] == "second-change"

    def test_studio_instructions_carry_run_guidance(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        instructions = studio.instructions or ""
        assert "sequentially" in instructions
        assert "ambiguous display name" in instructions.lower()
