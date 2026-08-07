"""Unit tests for StudioRunnerTools -- and StudioTools' embedding of it.

Uses a real SqliteDb backed by a pytest tmp_path so component persistence and
name/slug resolution run against the full storage path, not mocks. Run
execution is exercised through stub components that capture the identity and
stream kwargs the runner threads through.
"""

import json
from typing import Any, Dict, List, Literal, Optional

import pytest
from pydantic import BaseModel

from agno.db.base import ComponentVersionGuard
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.tools.function import FunctionCall
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import ComponentNeedsRegistryError, StudioRunnerTools
from agno.tools.studio_schema import (
    AgentCreate,
    AgentPatch,
    AgentWorkflowStep,
    ComponentRef,
    FunctionWorkflowStep,
    ModelRef,
    StudioResult,
    TeamCreate,
    TeamPatch,
    ToolRef,
    WorkflowCreate,
    WorkflowPatch,
)

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


def _authorize_studio(_run_context: RunContext, _access: str, _action: str) -> bool:
    return True


def _studio(registry: Registry, db: SqliteDb, **kwargs: Any) -> StudioTools:
    return StudioTools(registry=registry, db=db, authorize=_authorize_studio, **kwargs)


def _data(result: StudioResult[Any]) -> Any:
    assert result.ok, result.error
    assert result.data is not None
    return result.data


def _agent_request(
    name: str,
    instructions: str = "i",
    *,
    component_id: Optional[str] = None,
    description: Optional[str] = None,
    tools: Optional[List[ToolRef]] = None,
) -> AgentCreate:
    return AgentCreate(
        component_id=component_id,
        name=name,
        instructions=instructions,
        description=description,
        model=ModelRef(id="gpt-5.4"),
        tools=tools or [],
    )


def _team_request(
    name: str,
    members: List[ComponentRef],
    instructions: str = "i",
    *,
    component_id: Optional[str] = None,
) -> TeamCreate:
    return TeamCreate(
        component_id=component_id,
        name=name,
        instructions=instructions,
        members=members,
        model=ModelRef(id="gpt-5.4"),
    )


def _workflow_request(
    name: str,
    steps: List[AgentWorkflowStep],
    *,
    component_id: Optional[str] = None,
    description: Optional[str] = "d",
) -> WorkflowCreate:
    return WorkflowCreate(component_id=component_id, name=name, description=description, steps=steps)


def _create_agent(
    studio: StudioTools, request: AgentCreate, *, save_as: Literal["draft", "published"] = "published"
) -> Any:
    return _data(studio.create_agent(request, save_as=save_as, _agno_run_context=_context()))


def _create_team(
    studio: StudioTools, request: TeamCreate, *, save_as: Literal["draft", "published"] = "published"
) -> Any:
    return _data(studio.create_team(request, save_as=save_as, _agno_run_context=_context()))


def _create_workflow(
    studio: StudioTools, request: WorkflowCreate, *, save_as: Literal["draft", "published"] = "published"
) -> Any:
    return _data(studio.create_workflow(request, save_as=save_as, _agno_run_context=_context()))


def _sub_session(component_type: str, component_id: str, caller_session: str = "caller-sess") -> Optional[str]:
    """The sub-session the runner derives for a caller. A digest, so the tests
    assert the derivation rather than a literal; see TestSubSessionDerivation for
    the properties that derivation has to hold."""
    return StudioRunnerTools._sub_session_id(_context(session_id=caller_session), component_type, component_id)


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


PRIVATE_RUNTIME_ERROR = "postgres://admin:private-password@db.internal/catalog"


class _FailingAgent(_StubAgent):
    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(PRIVATE_RUNTIME_ERROR)

    async def arun(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(PRIVATE_RUNTIME_ERROR)


class _FailingTeam(_StubTeam):
    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(PRIVATE_RUNTIME_ERROR)

    async def arun(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(PRIVATE_RUNTIME_ERROR)


class _FailingWorkflow(_StubWorkflow):
    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(PRIVATE_RUNTIME_ERROR)

    async def arun(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(PRIVATE_RUNTIME_ERROR)


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

    def test_model_guidance_does_not_promise_slug_aliases_for_explicit_ids(self, db):
        runner = StudioRunnerTools(db=db)
        instructions = str(runner.instructions or "")
        assert "Use the exact id from a list tool; an exact display name also resolves" in instructions
        assert "display name or its slug" not in instructions

        for functions in (runner.functions, runner.async_functions):
            function = functions["run_agent"]
            function.process_entrypoint()
            agent_id_description = function.parameters["properties"]["agent_id"]["description"]
            assert "Exact agent id, or an exact display name" in agent_id_description
            assert "or its slug" not in agent_id_description


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
            "session_id": _sub_session("agent", "stub"),
        }
        assert out == {
            "agent_id": "stub",
            "run_id": "run-1",
            "session_id": "sub-sess-1",
            "status": "COMPLETED",
            "content": "done",
        }

    def test_sessionless_run_passes_no_session_id(self, db):
        # A caller with no session of its own -- a direct Python call, which takes
        # no session argument -- passes session_id=None to the target. The target
        # is a per-call copy or rebuild, so each such run starts a session of its
        # own; a component constructed with an explicit session_id keeps using it.
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("stub", "hi"))
        assert stub.seen is not None and stub.seen["user_id"] is None
        assert stub.seen["session_id"] is None
        runner.run_agent("stub", "hi")
        assert stub.seen is not None and stub.seen["session_id"] is None
        assert out["status"] == "COMPLETED"

    def test_run_agent_resolves_code_defined_by_name(self, db):
        stub = _StubAgent()
        runner = StudioRunnerTools(db=db, agents_list=[stub])
        out = _loads(runner.run_agent("Stub", "hi", _agno_run_context=_context()))
        assert "error" not in out
        # The payload and the derived session both carry the component's real id.
        assert out["agent_id"] == "stub"
        assert stub.seen is not None and stub.seen["session_id"] == _sub_session("agent", "stub")

    def test_run_team_threads_identity(self, db):
        stub = _StubTeam()
        runner = StudioRunnerTools(db=db, teams_list=[stub])
        out = _loads(runner.run_team("stub-team", "hi", _agno_run_context=_context()))
        assert stub.seen == {
            "message": "hi",
            "stream": False,
            "user_id": "ash",
            "session_id": _sub_session("team", "stub-team"),
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
            "session_id": _sub_session("workflow", "stub-wf"),
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
            "session_id": _sub_session("agent", "stub"),
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

    @pytest.mark.asyncio
    async def test_arun_team_and_workflow_thread_identity(self, db):
        # Whole-dict asserts, mirroring the sync twins: a dropped user_id or
        # session on the async path must fail, not pass by partial match.
        team = _StubTeam()
        wf = _StubWorkflow()
        runner = StudioRunnerTools(db=db, teams_list=[team], workflows_list=[wf])
        await runner.arun_team("stub-team", "hi", _agno_run_context=_context())
        await runner.arun_workflow("stub-wf", "go", _agno_run_context=_context())
        assert team.seen == {
            "message": "hi",
            "stream": False,
            "user_id": "ash",
            "session_id": _sub_session("team", "stub-team"),
        }
        assert wf.seen == {
            "input": "go",
            "stream": False,
            "user_id": "ash",
            "session_id": _sub_session("workflow", "stub-wf"),
        }


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
        assert stub.seen["session_id"] == _sub_session("agent", "stub")

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
# Resolution: exact ids, exact display names, ambiguity, and no slug aliases
# ----------------------------------------------------------------------


class TestResolution:
    def test_find_agent_resolves_db_component_by_display_name(self, registry, db):
        studio = _studio(registry, db)
        created = _create_agent(studio, _agent_request("Radar Scout"))
        assert created.component_id == "radar-scout"

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
        studio = _studio(registry, db, teams=True)
        _create_agent(studio, _agent_request("member"))
        _create_team(
            studio,
            _team_request("squad", [ComponentRef(component_type="agent", component_id="member")]),
        )

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
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("radar"))
        shadow = _StubAgent()
        shadow.id = "other"
        shadow.name = "radar"
        runner = StudioRunnerTools(registry=registry, db=db, agents_list=[shadow])
        found = runner._find_agent("radar")
        assert found is not shadow
        assert getattr(found, "id", None) == "radar"

    def test_display_name_resolves_across_type_slug_collision(self, registry, db):
        # Stable ids are global, while display-name resolution remains typed.
        studio = _studio(registry, db, teams=True)
        _create_agent(studio, _agent_request("member"))
        _create_team(
            studio,
            _team_request(
                "Radar Scout",
                [ComponentRef(component_type="agent", component_id="member")],
                component_id="radar-scout-team",
            ),
        )
        created = _create_agent(
            studio,
            _agent_request("Radar Scout", component_id="radar-scout-agent"),
        )
        assert created.component_id == "radar-scout-agent"

        runner = StudioRunnerTools(registry=registry, db=db)
        agent = runner._find_agent("Radar Scout")
        team = runner._find_team("Radar Scout")
        assert agent is not None and agent.id == "radar-scout-agent"
        assert team is not None and team.id == "radar-scout-team"

    def test_display_name_slug_is_not_an_alias_for_an_explicit_component_id(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(
            studio,
            _agent_request("Radar Scout", component_id="radar-scout-agent"),
        )

        runner = StudioRunnerTools(registry=registry, db=db)
        assert runner._find_agent("Radar Scout") is not None
        assert runner._find_agent("radar-scout") is None
        assert runner._find_agent("radar-scout-agent") is not None

    def test_ambiguous_display_name_errors_with_matching_ids(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout", component_id="radar-scout"))
        _create_agent(studio, _agent_request("Radar Scout", component_id="radar-scout-2"))

        runner = StudioRunnerTools(registry=registry, db=db)
        out = _loads(runner.run_agent("Radar Scout", "hi"))
        assert "Ambiguous" in out["error"]
        assert "radar-scout" in out["error"] and "radar-scout-2" in out["error"]
        # Exact ids stay unambiguous.
        found = runner._find_agent("radar-scout-2")
        assert found is not None and found.id == "radar-scout-2"

    @pytest.mark.asyncio
    async def test_async_ambiguous_display_name_errors(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout", component_id="radar-scout"))
        _create_agent(studio, _agent_request("Radar Scout", component_id="radar-scout-2"))

        runner = StudioRunnerTools(registry=registry, db=db)
        out = _loads(await runner.arun_agent("Radar Scout", "hi"))
        assert "Ambiguous" in out["error"]

    def test_fuzzy_display_name_is_not_inferred_as_an_id(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout"))

        runner = StudioRunnerTools(registry=registry, db=db)
        assert runner._find_agent("radar scout!") is None

    def test_name_lookup_pages_beyond_first_page(self, registry, db, monkeypatch):
        import agno.tools.studio_runner as studio_runner_module

        monkeypatch.setattr(studio_runner_module, "_NAME_LOOKUP_PAGE", 1)
        studio = _studio(registry, db)
        for name in ("Oldest Match", "newer-a", "newer-b"):
            _create_agent(studio, _agent_request(name))

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

        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Reports", component_id="reports"))
        created = _create_agent(studio, _agent_request("reports", component_id="reports-2"))
        assert created.component_id == "reports-2"

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

    def test_db_failure_during_resolution_is_sanitized(self, db, caplog):
        runner = StudioRunnerTools(db=db)

        def boom(*args, **kwargs):
            raise RuntimeError(PRIVATE_RUNTIME_ERROR)

        runner.db.list_components = boom  # type: ignore[method-assign]
        out = _loads(runner.run_agent("Some Name", "hi"))
        assert out == {"error": "StudioRunnerTools could not resolve agent."}
        assert PRIVATE_RUNTIME_ERROR not in json.dumps(out)
        assert PRIVATE_RUNTIME_ERROR not in caplog.text


class TestUnexpectedFailureSanitization:
    def test_deep_copy_failure_does_not_expose_exception_text(self, db, caplog):
        class _SecretCopyAgent(_StubAgent):
            def deep_copy(self):
                raise RuntimeError(PRIVATE_RUNTIME_ERROR)

        runner = StudioRunnerTools(db=db, agents_list=[_SecretCopyAgent()])

        out = _loads(runner.run_agent("stub", "hi"))

        assert "deep_copy failed for 'stub'" in out["error"]
        assert PRIVATE_RUNTIME_ERROR not in json.dumps(out)
        assert PRIVATE_RUNTIME_ERROR not in caplog.text

    @pytest.mark.parametrize(
        ("component_type", "method_name", "component_id", "component"),
        [
            ("agent", "run_agent", "stub", _FailingAgent()),
            ("team", "run_team", "stub-team", _FailingTeam()),
            ("workflow", "run_workflow", "stub-wf", _FailingWorkflow()),
        ],
    )
    def test_sync_runtime_errors_are_sanitized(
        self,
        db,
        caplog,
        component_type: str,
        method_name: str,
        component_id: str,
        component: Any,
    ):
        runner = StudioRunnerTools(db=db, **{f"{component_type}s_list": [component]})

        out = _loads(getattr(runner, method_name)(component_id, "hi", _agno_run_context=_context()))

        assert out == {"error": f"StudioRunnerTools could not run {component_type}."}
        assert PRIVATE_RUNTIME_ERROR not in json.dumps(out)
        assert PRIVATE_RUNTIME_ERROR not in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("component_type", "method_name", "component_id", "component"),
        [
            ("agent", "arun_agent", "stub", _FailingAgent()),
            ("team", "arun_team", "stub-team", _FailingTeam()),
            ("workflow", "arun_workflow", "stub-wf", _FailingWorkflow()),
        ],
    )
    async def test_async_runtime_errors_are_sanitized(
        self,
        db,
        caplog,
        component_type: str,
        method_name: str,
        component_id: str,
        component: Any,
    ):
        runner = StudioRunnerTools(db=db, **{f"{component_type}s_list": [component]})

        out = _loads(await getattr(runner, method_name)(component_id, "hi", _agno_run_context=_context()))

        assert out == {"error": f"StudioRunnerTools could not run {component_type}."}
        assert PRIVATE_RUNTIME_ERROR not in json.dumps(out)
        assert PRIVATE_RUNTIME_ERROR not in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("component_type", "method_name", "resolver_name"),
        [
            ("agent", "arun_agent", "_agent_for_run"),
            ("team", "arun_team", "_team_for_run"),
            ("workflow", "arun_workflow", "_workflow_for_run"),
        ],
    )
    async def test_async_resolution_errors_are_sanitized(
        self,
        db,
        caplog,
        monkeypatch: pytest.MonkeyPatch,
        component_type: str,
        method_name: str,
        resolver_name: str,
    ):
        runner = StudioRunnerTools(db=db)

        def fail_resolution(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(PRIVATE_RUNTIME_ERROR)

        monkeypatch.setattr(runner, resolver_name, fail_resolution)
        out = _loads(await getattr(runner, method_name)("hidden", "hi"))

        assert out == {"error": f"StudioRunnerTools could not resolve {component_type}."}
        assert PRIVATE_RUNTIME_ERROR not in json.dumps(out)
        assert PRIVATE_RUNTIME_ERROR not in caplog.text


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
        assert agent.seen["session_id"] == _sub_session("agent", "shared")
        assert team.seen["session_id"] == _sub_session("team", "shared")

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

        class _SelfCopyAgent(_StubAgent):
            def deep_copy(self):
                return self

        class _BaseClassCopyAgent(_StubAgent):
            def deep_copy(self):
                copy = _StubAgent()
                copy.id = self.id
                copy.name = self.name
                return copy

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

        selfish = _SelfCopyAgent()
        runner = StudioRunnerTools(db=db, agents_list=[selfish])
        out = _loads(runner.run_agent("stub", "hi"))
        assert "returned the shared instance" in out["error"]
        assert selfish.seen is None

        downcast = _BaseClassCopyAgent()
        runner = StudioRunnerTools(db=db, agents_list=[downcast])
        out = _loads(runner.run_agent("stub", "hi"))
        assert "lost its identity" in out["error"]
        assert downcast.seen is None

    def test_copy_dropping_model_instructions_or_member_isolation_refuses_dispatch(self, db):
        # The fidelity loop checks model, instructions and member isolation, not
        # only id and name: a rebuild that keeps the identity fields but drops
        # what the component thinks with -- or shares its member objects -- must
        # not be dispatched silently degraded.
        class _ModelDroppingAgent(_StubAgent):
            model = "gpt-x"

            def deep_copy(self):
                clone = object.__new__(type(self))
                clone.__dict__ = dict(self.__dict__)
                clone.model = None
                return clone

        class _InstructionsDroppingAgent(_StubAgent):
            instructions = "be nice"

            def deep_copy(self):
                clone = object.__new__(type(self))
                clone.__dict__ = dict(self.__dict__)
                clone.instructions = None
                return clone

        class _MemberSharingTeam(_StubTeam):
            def __init__(self):
                super().__init__()
                self.members = [_StubAgent()]

            def deep_copy(self):
                clone = object.__new__(type(self))
                clone.__dict__ = dict(self.__dict__)
                return clone

        for agent_cls in (_ModelDroppingAgent, _InstructionsDroppingAgent):
            agent = agent_cls()
            runner = StudioRunnerTools(db=db, agents_list=[agent])
            out = _loads(runner.run_agent("stub", "hi"))
            assert "lost its identity" in out["error"]
            assert agent.seen is None

        team = _MemberSharingTeam()
        runner = StudioRunnerTools(db=db, teams_list=[team])
        out = _loads(runner.run_team("stub-team", "hi"))
        assert "still shares member 'stub' with the original" in out["error"]
        assert team.seen is None

    def test_fresh_copy_of_real_components_preserves_fidelity(self, db):
        # Pins the agno deep_copy <-> _fresh_copy contract with the real
        # classes: a dispatch copy is distinct, keeps what the component says
        # and thinks with, and holds no shared member objects.
        from agno.agent.agent import Agent as AgentClass
        from agno.team.team import Team as TeamClass

        member_a = AgentClass(id="m-a", name="A")
        member_b = AgentClass(id="m-b", name="B")
        agent = AgentClass(id="real-agent", name="Real", instructions="be real")
        team = TeamClass(id="real-team", name="Real Team", members=[member_a, member_b])
        runner = StudioRunnerTools(db=db, agents_list=[agent], teams_list=[team])

        fresh_agent = runner._agent_for_run("real-agent")
        assert fresh_agent is not None and fresh_agent is not agent
        assert (fresh_agent.id, fresh_agent.name, fresh_agent.instructions) == ("real-agent", "Real", "be real")

        fresh_team = runner._team_for_run("real-team")
        assert fresh_team is not None and fresh_team is not team
        assert fresh_team.id == "real-team"
        assert fresh_team.members
        assert all(member is not member_a and member is not member_b for member in fresh_team.members)

    def test_blank_copy_with_no_id_refuses_dispatch(self, db):
        # A subclass whose __init__ hides the dataclass fields rebuilds blank.
        # With no id on either side the id comparison is vacuous; the name
        # comparison still catches the blank copy.
        class _BlankCopyAgent(_StubAgent):
            id = None
            name = "Helper"

            def deep_copy(self):
                blank = object.__new__(type(self))
                blank.__dict__ = dict(self.__dict__)
                blank.name = None
                return blank

        blank = _BlankCopyAgent()
        runner = StudioRunnerTools(db=db, agents_list=[blank])
        out = _loads(runner.run_agent("Helper", "hi"))
        assert "lost its identity" in out["error"]
        assert blank.seen is None

    def test_loader_keeps_config_declared_db(self, registry, db, tmp_path, monkeypatch):
        # A db reconstructed from the component's own config (possibly carrying
        # table overrides) must not be overwritten by the catalog db.
        from agno.agent.agent import Agent as AgentClass

        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar"))

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
    def test_list_agents_reports_what_dispatch_admits(self, registry, db):
        # The instructions tell the caller to list first and run by id, so a
        # component that runs and cannot be found leaves it no way in. An
        # explicit agents_list is an allowlist FOR dispatch, so it is listed --
        # code first, which is the order dispatch resolves in.
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar", description="scans the week"))

        runner = StudioRunnerTools(registry=registry, db=db, agents_list=[_StubAgent()])
        out = _loads(runner.list_agents())
        assert out["agents"][-1] == {"id": "radar", "name": "Radar", "description": "scans the week"}
        assert any(entry["id"] == _StubAgent().id for entry in out["agents"])
        assert out["count"] == len(out["agents"])
        assert out["total"] == 2

    def test_a_registry_agent_stays_unlisted_until_it_is_admitted(self, registry, db):
        # The privacy half of the rule is unchanged: a registry is passed so
        # persisted components can rehydrate, which is not consent to run --
        # or to advertise -- every agent the application happens to define.
        from agno.agent import Agent

        registry.agents = [Agent(id="internal", name="Internal", model=OpenAIResponses(id="gpt-5.4"))]
        unadmitted = _loads(StudioRunnerTools(registry=registry, db=db).list_agents())
        assert all(entry["id"] != "internal" for entry in unadmitted["agents"])

        admitted = _loads(StudioRunnerTools(registry=registry, db=db, include_all_components=True).list_agents())
        assert any(entry["id"] == "internal" for entry in admitted["agents"])

    def test_list_agents_reports_total_beyond_cap(self, registry, db):
        studio = _studio(registry, db)
        for name in ("one", "two", "three"):
            _create_agent(studio, _agent_request(name))

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

    def test_list_failure_does_not_expose_exception_text(self, db, caplog):
        def fail_list(*_args, **_kwargs):
            raise RuntimeError(PRIVATE_RUNTIME_ERROR)

        db.list_components = fail_list
        runner = StudioRunnerTools(db=db)

        out = _loads(runner.list_agents())

        assert out == {"error": "StudioRunnerTools could not list agents."}
        assert PRIVATE_RUNTIME_ERROR not in json.dumps(out)
        assert PRIVATE_RUNTIME_ERROR not in caplog.text


# ----------------------------------------------------------------------
# StudioTools embedding
# ----------------------------------------------------------------------


class TestStudioEmbedding:
    def test_public_run_methods_forward_to_the_runner(self, registry, db):
        stub = _StubAgent()
        studio = _studio(registry, db, agents_list=[stub])
        for name in ("run_agent", "run_team", "run_workflow", "arun_agent", "arun_team", "arun_workflow"):
            assert hasattr(studio, name)
        out = _loads(studio.run_agent("stub", "hi", _agno_run_context=_context()))
        assert out["agent_id"] == "stub"
        assert stub.seen is not None

    @pytest.mark.asyncio
    async def test_public_arun_agent_forwards_to_the_runner(self, registry, db):
        stub = _StubAgent()
        studio = _studio(registry, db, agents_list=[stub])
        out = _loads(await studio.arun_agent("stub", "hi", _agno_run_context=_context()))
        assert out["agent_id"] == "stub"

    def test_studio_registers_its_own_run_methods(self, registry, db):
        # The registered tool must be StudioTools' own method, not the embedded
        # runner's bound method, or a subclass override never sits on the path the
        # model takes.
        studio = _studio(registry, db, teams=True, workflows=True)
        for name in ("run_agent", "run_team", "run_workflow"):
            entrypoint = studio.functions[name].entrypoint
            assert getattr(entrypoint, "__self__", None) is studio
            async_entrypoint = studio.async_functions[name].entrypoint
            assert getattr(async_entrypoint, "__self__", None) is studio

    def test_studio_subclass_override_is_what_the_model_calls(self, registry, db):
        calls: List[str] = []

        class Guarded(StudioTools):
            def run_agent(self, agent_id, message, _agno_run_context=None):
                calls.append(agent_id)
                return super().run_agent(agent_id, message, _agno_run_context)

        stub = _StubAgent()
        studio = Guarded(
            registry=registry,
            db=db,
            authorize=_authorize_studio,
            agents_list=[stub],
        )
        out = _loads(studio.functions["run_agent"].entrypoint("stub", "hi", _agno_run_context=_context()))
        assert calls == ["stub"]
        assert out["agent_id"] == "stub"
        assert "id" not in out

    def test_identity_threads_through_studio_registered_tool(self, registry, db):
        stub = _StubAgent()
        studio = _studio(registry, db, agents_list=[stub])
        out = _loads(studio.functions["run_agent"].entrypoint("stub", "hi", _agno_run_context=_context()))
        assert stub.seen == {
            "message": "hi",
            "stream": False,
            "user_id": "ash",
            "session_id": _sub_session("agent", "stub"),
        }
        assert out["agent_id"] == "stub"

    def test_studio_lookup_uses_exact_component_id(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout"))
        missing = studio.get_agent("Radar Scout", _agno_run_context=_context())
        assert missing.error is not None and missing.error.code == "invalid_component_id"
        assert _data(studio.get_agent("radar-scout", _agno_run_context=_context())).component_id == "radar-scout"

    def test_same_display_name_is_safe_with_exact_component_ids(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout", component_id="radar-a"))
        _create_agent(studio, _agent_request("Radar Scout", component_id="radar-b"))
        first = _data(studio.get_agent("radar-a", _agno_run_context=_context()))
        second = _data(studio.get_agent("radar-b", _agno_run_context=_context()))
        assert first.component_id == "radar-a"
        assert second.component_id == "radar-b"

    def test_edit_uses_exact_component_id(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout"))
        out = studio.edit_agent(
            "radar-scout",
            AgentPatch(instructions="updated"),
            expected_version=1,
            save_as="published",
            _agno_run_context=_context(),
        )
        assert out.ok and out.status == "edited"
        assert out.data is not None and out.data.component_id == "radar-scout"
        fetched = _data(studio.get_agent("radar-scout", _agno_run_context=_context()))
        assert fetched.instructions == "updated"

    def test_exact_team_member_id_beats_agent_display_name(self, registry, db):
        studio = _studio(registry, db, teams=True)
        _create_agent(studio, _agent_request("member"))
        _create_team(
            studio,
            _team_request(
                "support",
                [ComponentRef(component_type="agent", component_id="member")],
                component_id="support-team",
            ),
        )
        _create_agent(studio, _agent_request("support", component_id="support-agent"))

        created = _create_team(
            studio,
            _team_request(
                "squad",
                [ComponentRef(component_type="team", component_id="support-team")],
            ),
        )
        assert created.members == [ComponentRef(component_type="team", component_id="support-team", version=1)]

    def test_list_shows_db_component_named_like_a_code_id(self, registry, db):
        code_agent = _StubAgent()
        code_agent.id = "support"
        code_agent.name = "Support Code"
        shadowed = _studio(registry, db, agents_list=[code_agent])
        created = _create_agent(
            shadowed,
            _agent_request("Support Code", component_id="support-db"),
        )
        assert created.component_id == "support-db"

        listed = _data(shadowed.list_agents(_agno_run_context=_context()))
        ids = {row.component_id for row in listed}
        assert "support" in ids
        assert "support-db" in ids

    def test_exact_db_id_remains_editable_when_code_name_collides(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout"))
        shadow = _StubAgent()
        shadow.id = "code-1"
        shadow.name = "Radar Scout"
        shadowed = _studio(registry, db, agents_list=[shadow])
        out = shadowed.edit_agent(
            "radar-scout",
            AgentPatch(instructions="x"),
            expected_version=1,
            save_as="published",
            _agno_run_context=_context(),
        )
        assert out.ok
        assert out.data is not None and out.data.component_id == "radar-scout"

    def test_typed_member_ref_rejects_cross_source_id_collision(self, registry, db):
        studio = _studio(registry, db, teams=True)
        _create_agent(studio, _agent_request("helper"))
        _create_team(
            studio,
            _team_request(
                "shared",
                [ComponentRef(component_type="agent", component_id="helper")],
            ),
        )
        code_agent = _StubAgent()
        code_agent.id = "shared"
        code_agent.name = "Shared Agent"
        shadowed = _studio(registry, db, teams=True, agents_list=[code_agent])
        result = shadowed.create_team(
            _team_request("squad", [ComponentRef(component_type="team", component_id="shared")]),
            _agno_run_context=_context(),
        )
        assert not result.ok
        assert result.error is not None and result.error.code == "component_source_collision"

    def test_typed_member_ref_ignores_cross_type_name_collision(self, registry, db):
        studio = _studio(registry, db, teams=True)
        _create_agent(studio, _agent_request("Ops", component_id="ops-agent"))
        _create_agent(studio, _agent_request("helper"))
        _create_team(
            studio,
            _team_request(
                "Ops",
                [ComponentRef(component_type="agent", component_id="helper")],
                component_id="ops-team",
            ),
        )
        created = _create_team(
            studio,
            _team_request("squad", [ComponentRef(component_type="team", component_id="ops-team")]),
        )
        assert created.members[0].component_id == "ops-team"

    def test_registry_less_runner_refuses_tool_bearing_component(self, db):
        from agno.tools.calculator import CalculatorTools

        armed_registry = Registry(
            name="Armed Registry",
            models=[OpenAIResponses(id="gpt-5.4")],
            tools=[CalculatorTools()],
            dbs=[db],
        )
        studio = _studio(armed_registry, db)
        _create_agent(
            studio,
            _agent_request("Armed", tools=[ToolRef(kind="toolkit", name="calculator")]),
        )
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
        studio = _studio(armed_registry, db, teams=True)
        _create_agent(
            studio,
            _agent_request("Armed", tools=[ToolRef(kind="toolkit", name="calculator")]),
        )
        _create_team(
            studio,
            _team_request("Crew", [ComponentRef(component_type="agent", component_id="armed")]),
        )

        runner = StudioRunnerTools(db=db)
        out = _loads(runner.run_team("crew", "hi"))
        assert "registry" in out.get("error", "")

    def test_incomplete_registry_refuses_a_tool_bearing_nested_member(self, db):
        # A member and a step executor rebuild from configs of their own, so the
        # parent's config check says nothing about them: with a registry that
        # holds the model but not the tool, the nested agent rebuilds with
        # entrypoint=None tools and would otherwise run stripped of them.
        from agno.tools.calculator import CalculatorTools

        armed_registry = Registry(
            name="Armed Registry",
            models=[OpenAIResponses(id="gpt-5.4")],
            tools=[CalculatorTools()],
            dbs=[db],
        )
        studio = _studio(armed_registry, db, teams=True, workflows=True)
        _create_agent(
            studio,
            _agent_request("Armed", tools=[ToolRef(kind="toolkit", name="calculator")]),
        )
        _create_team(
            studio,
            _team_request("Crew", [ComponentRef(component_type="agent", component_id="armed")]),
        )
        _create_workflow(
            studio,
            _workflow_request(
                "Flow",
                [AgentWorkflowStep(kind="agent", name="s1", component_id="armed")],
            ),
        )

        toolless_registry = Registry(name="Toolless", models=[OpenAIResponses(id="gpt-5.4")], dbs=[db])
        runner = StudioRunnerTools(registry=toolless_registry, db=db)

        out = _loads(runner.run_team("crew", "hi"))
        # The refusal names the nested member and the tool functions it lost.
        assert "nested component armed" in out.get("error", "")
        assert "add" in out.get("error", "")

        out = _loads(runner.run_workflow("flow", "go"))
        assert "nested component armed" in out.get("error", "")
        assert "add" in out.get("error", "")

        # The complete registry still dispatches: the guard refuses degradation,
        # not composition.
        complete = StudioRunnerTools(registry=armed_registry, db=db)
        assert complete._team_for_run("crew") is not None

    def test_registry_less_runner_refuses_workflow_with_code_defined_step(self, registry, db):
        code_agent = _StubAgent()
        studio = _studio(registry, db, workflows=True, agents_list=[code_agent])
        created = _create_workflow(
            studio,
            _workflow_request(
                "Flow",
                [AgentWorkflowStep(kind="agent", name="s1", component_id="stub")],
            ),
            save_as="draft",
        )
        assert created.stage == "draft"

        # Persisted legacy/external configs can still carry code-defined refs;
        # runner dispatch must fail closed without the registry.
        db.upsert_config(
            component_id="flow",
            version=1,
            stage="published",
            guard=ComponentVersionGuard(latest_version=1, current_version=None),
        )

        runner = StudioRunnerTools(db=db)
        out = _loads(runner.run_workflow("flow", "go"))
        assert "registry" in out.get("error", "")
        assert "not found" not in out.get("error", "")

    def test_registry_less_runner_refuses_knowledge_bearing_component(self, db):
        # A knowledge reference is stored as {"name": ...} and resolves only
        # through the registry; a registry-less rebuild would drop it and run
        # the agent without retrieval.
        config = {
            "id": "rag",
            "model": {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"},
            "instructions": "answer from the handbook",
            "knowledge": {"name": "handbook"},
        }
        db.upsert_component(component_id="rag", component_type="agent", name="RagBot")
        db.upsert_config(component_id="rag", config=config, stage="published")

        out = _loads(StudioRunnerTools(db=db).run_agent("rag", "hi"))
        assert "knowledge" in out.get("error", "")
        assert "registry" in out.get("error", "")

    def test_unresolved_tools_inside_a_compound_step_are_refused(self, db, registry):
        """A step reached through a compound step's branch list is a step, not an
        executor, so a walk that unwraps executors only one level below the
        workflow never reaches it. The same agent as a direct step was already
        refused; nesting it must not buy dispatch."""
        from agno.tools.calculator import CalculatorTools
        from agno.workflow.parallel import Parallel
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        armed_registry = Registry(
            name="Armed Registry", models=[OpenAIResponses(id="gpt-5.4")], tools=[CalculatorTools()], dbs=[db]
        )
        studio = _studio(armed_registry, db, workflows=True)
        _create_agent(
            studio,
            _agent_request("Armed", tools=[ToolRef(kind="toolkit", name="calculator")]),
        )
        _create_workflow(
            studio,
            _workflow_request(
                "Direct",
                [AgentWorkflowStep(kind="agent", name="s", component_id="armed")],
            ),
        )
        # StudioTools cannot author a compound step, so the persisted config for
        # the nested shape is written directly, the way a posted config arrives.
        db.upsert_component(component_id="nested", component_type="workflow", name="Nested")
        db.upsert_config(
            component_id="nested",
            stage="published",
            config={
                "id": "nested",
                "name": "Nested",
                "steps": [{"name": "p", "type": "Parallel", "steps": [{"name": "s", "agent_id": "armed"}]}],
            },
        )

        # The registry resolves the model but not the tool, so the rebuild binds
        # the tool to entrypoint=None rather than failing.
        runner = StudioRunnerTools(registry=registry, db=db)
        for workflow_id in ("direct", "nested"):
            assert "add" in _loads(runner.run_workflow(workflow_id, "hi")).get("error", ""), workflow_id

        # The walk used to alternate with nesting depth -- one wrapper missed,
        # two caught -- so a doubly nested spot check would have looked healthy.
        agent = runner._load_agent_from_db("armed")
        nested: Any = Step(name="s", agent=agent)
        for depth in range(1, 5):
            nested = Parallel(nested, name=f"p{depth}")
            wf = Workflow(id="w", name="W", steps=[nested])
            assert StudioRunnerTools._unresolved_below(wf) is not None, depth

    def test_nested_workflow_step_is_refused_rather_than_reported_complete(self, db, registry):
        """A nested workflow serializes as workflow_id alone and Step.from_dict
        installs a placeholder that returns an unsuccessful StepOutput. A failed
        step does not fail its workflow, so dispatching would report COMPLETED
        while the child never ran."""
        for component_id, config in (
            ("child", {"id": "child", "name": "Child", "steps": [{"name": "c", "agent_id": "worker"}]}),
            ("parent", {"id": "parent", "name": "Parent", "steps": [{"name": "call", "workflow_id": "child"}]}),
        ):
            db.upsert_component(component_id=component_id, component_type="workflow", name=component_id)
            db.upsert_config(component_id=component_id, config=config, stage="published")

        result = _loads(StudioRunnerTools(registry=registry, db=db).run_workflow("parent", "hi"))
        assert "cannot reconstruct" in result["error"]
        assert "child" in result["error"]

    def test_bare_executor_step_that_copies_to_itself_is_refused(self, db):
        """A workflow takes a bare agent as a step, without a Step wrapper. Then
        the item IS the executor, so a check that only reads item.agent/.team
        walks straight past it."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.workflow.workflow import Workflow

        class _SelfCopy(Agent):
            def deep_copy(self, *, update=None):
                return self

        leaky = _SelfCopy(id="leaky", name="Leaky", model=OpenAIResponses(id="gpt-5.4"))
        wf = Workflow(id="flow", name="Flow", db=db, steps=[leaky])
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, workflows_list=[wf])

        assert "is still shared" in _loads(runner.run_workflow("flow", "hi"))["error"]

    def test_degraded_copy_of_a_registered_component_is_refused(self, db, registry):
        """A deep_copy returning a distinct but blank object passes every
        identity check that asks "is this the same instance". The registry still
        holds the original, so the copy is judged against it."""
        from agno.agent import Agent

        class _Downcast(Agent):
            def deep_copy(self, *, update=None):
                return Agent(id=self.id, name=self.name)  # loses model and instructions

        worker = _Downcast(id="worker", name="Worker", model=OpenAIResponses(id="gpt-5.4"), instructions="rules")
        registry.agents = [worker]
        for component_id, component_type, config in (
            (
                "crew",
                "team",
                {
                    "id": "crew",
                    "name": "Crew",
                    "model": {"id": "gpt-5.4", "provider": "OpenAI"},
                    "members": [{"type": "agent", "agent_id": "worker"}],
                },
            ),
            ("flow", "workflow", {"id": "flow", "name": "Flow", "steps": [{"name": "s", "agent_id": "worker"}]}),
        ):
            db.upsert_component(component_id=component_id, component_type=component_type, name=component_id)
            db.upsert_config(component_id=component_id, config=config, stage="published")

        runner = StudioRunnerTools(registry=registry, db=db)
        assert "degraded copy" in _loads(runner.run_team("crew", "hi"))["error"]
        assert "degraded copy" in _loads(runner.run_workflow("flow", "hi"))["error"]

        # A faithful copy of the same registered component still dispatches.
        registry.agents = [Agent(id="worker", name="Worker", model=OpenAIResponses(id="gpt-5.4"))]
        assert StudioRunnerTools(registry=registry, db=db)._team_for_run("crew") is not None

    def test_references_are_checked_all_the_way_down(self, db, registry):
        """A reference's own config names references of its own. Stopping after
        one hop leaves an outer team dispatchable while its inner team's member
        lost the schema it declared."""

        class Report(BaseModel):
            title: str

        for component_id, component_type, config in (
            (
                "leaf",
                "agent",
                {
                    "id": "leaf",
                    "name": "leaf",
                    "model": {"id": "gpt-5.4", "provider": "OpenAI"},
                    "output_schema": "Report",
                },
            ),
            (
                "inner",
                "team",
                {
                    "id": "inner",
                    "name": "inner",
                    "model": {"id": "gpt-5.4", "provider": "OpenAI"},
                    "members": [{"type": "agent", "agent_id": "leaf"}],
                },
            ),
            (
                "outer",
                "team",
                {
                    "id": "outer",
                    "name": "outer",
                    "model": {"id": "gpt-5.4", "provider": "OpenAI"},
                    "members": [{"type": "team", "team_id": "inner"}],
                },
            ),
        ):
            db.upsert_component(component_id=component_id, component_type=component_type, name=component_id)
            db.upsert_config(component_id=component_id, config=config, stage="published")

        # The refusal has to name the piece that went missing; which layer
        # refuses it (this check, or a strict rehydration below it) may vary.
        assert "Report" in _loads(StudioRunnerTools(registry=registry, db=db).run_team("outer", "hi"))["error"]

        registry.schemas = [Report]
        whole = StudioRunnerTools(registry=registry, db=db)._team_for_run("outer")
        assert whole.members[0].members[0].output_schema is Report

    def test_a_graph_too_deep_to_inspect_is_refused_not_passed(self, db):
        """Every check here is depth-capped so a cycle cannot hang it, and a cap
        reached mid-walk reports nothing wrong. Past the cap that is a pass for
        a graph nobody inspected, so dispatch refuses instead."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.workflow.parallel import Parallel
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        def _wrapped(count: int, workflow_id: str):
            nested: Any = Step(name="s", agent=Agent(id="a", name="A", model=OpenAIResponses(id="gpt-5.4")))
            for index in range(count):
                nested = Parallel(nested, name=f"p{index}")
            return Workflow(id=workflow_id, name=workflow_id, db=db, steps=[nested])

        shallow, deep = _wrapped(4, "shallow"), _wrapped(40, "deep")
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, workflows_list=[shallow, deep])

        assert runner._workflow_for_run("shallow") is not None
        assert "nests deeper than" in _loads(runner.run_workflow("deep", "hi"))["error"]

    def test_a_registry_backed_step_executor_is_not_judged_against_a_stored_config(self, db, registry):
        """from_dict resolves an executor from the registry before the database,
        so a component that lives in both is the live object, not a rebuild of
        that config. A live toolkit is one object where the config lists its
        eight functions, and comparing the two called the healthy agent gutted."""
        from agno.agent import Agent
        from agno.tools.calculator import CalculatorTools

        live = Agent(id="worker", name="Worker", model=OpenAIResponses(id="gpt-5.4"), tools=[CalculatorTools()])
        registry.agents = [live]
        registry.tools = [CalculatorTools()]
        db.upsert_component(component_id="worker", component_type="agent", name="Worker")
        # The stored config lists the toolkit's functions one by one, the shape
        # the live object holds as a single toolkit.
        db.upsert_config(
            component_id="worker",
            stage="published",
            config={
                "id": "worker",
                "name": "Worker",
                "model": {"id": "gpt-5.4", "provider": "OpenAI"},
                "tools": [{"name": name} for name in ("add", "subtract", "multiply", "divide")],
            },
        )
        db.upsert_component(component_id="flow", component_type="workflow", name="Flow")
        db.upsert_config(
            component_id="flow",
            stage="published",
            config={"id": "flow", "name": "Flow", "steps": [{"name": "s", "agent_id": "worker"}]},
        )

        runner = StudioRunnerTools(registry=registry, db=db)
        dispatched = runner._workflow_for_run("flow")
        assert dispatched is not None
        # The live toolkit came through, which is what the config's expanded
        # function list would have been compared against.
        assert dispatched.steps[0].agent.tools

    def test_an_empty_branch_list_is_a_shape_not_a_loss(self, db):
        """Condition(else_steps=[]) declares no else branch. Reading an empty
        list as "the copy dropped these steps" refuses a clean workflow."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.workflow.condition import Condition
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        agent = Agent(id="a", name="A", model=OpenAIResponses(id="gpt-5.4"))
        condition = Condition(name="c", evaluator=lambda *_: True, steps=[Step(name="s", agent=agent)], else_steps=[])
        wf = Workflow(id="cond", name="cond", db=db, steps=[condition])
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, workflows_list=[wf])

        assert runner._workflow_for_run("cond") is not None

    def test_a_steps_container_is_walked_like_a_step_list(self, db):
        """steps= takes a list or one compound step. A check that only handles
        the list spelling skips the whole workflow when it is given a container."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps
        from agno.workflow.workflow import Workflow

        class _SelfCopy(Agent):
            def deep_copy(self, *, update=None):
                return self

        leaky = _SelfCopy(id="leaky", name="Leaky", model=OpenAIResponses(id="gpt-5.4"))
        wf = Workflow(id="boxed", name="boxed", db=db, steps=Steps(name="box", steps=[Step(name="s", agent=leaky)]))
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, workflows_list=[wf])

        assert "is still shared" in _loads(runner.run_workflow("boxed", "hi"))["error"]

    def test_only_a_steps_own_workflow_id_marks_a_nested_workflow(self, db, registry):
        """A step carries free-form user JSON as well as its own fields, so a
        walk over every value refuses on a key that merely shares the name."""
        db.upsert_component(component_id="a1", component_type="agent", name="a1")
        db.upsert_config(
            component_id="a1",
            stage="published",
            config={"id": "a1", "name": "a1", "model": {"id": "gpt-5.4", "provider": "OpenAI"}},
        )
        db.upsert_component(component_id="fy", component_type="workflow", name="fy")
        db.upsert_config(
            component_id="fy",
            stage="published",
            config={
                "id": "fy",
                "name": "fy",
                "steps": [
                    {
                        "type": "Step",
                        "name": "s",
                        "agent_id": "a1",
                        "human_review": {"user_input_schema": [{"name": "target", "workflow_id": "other-flow"}]},
                    }
                ],
            },
        )

        runner = StudioRunnerTools(registry=registry, db=db)
        assert "cannot reconstruct" not in _loads(runner.run_workflow("fy", "hi")).get("error", "")

    def test_a_failed_reference_read_refuses_without_exposing_exception_text(self, db, registry, caplog):
        """A db read that fails is not evidence of fidelity. Swallowing it would
        turn "could not check" into "checked and fine" for the one component the
        check exists to inspect."""
        db.upsert_component(component_id="worker", component_type="agent", name="Worker")
        db.upsert_config(
            component_id="worker",
            stage="published",
            config={"id": "worker", "name": "Worker", "model": {"id": "gpt-5.4", "provider": "OpenAI"}},
        )
        db.upsert_component(component_id="crew", component_type="team", name="Crew")
        db.upsert_config(
            component_id="crew",
            stage="published",
            config={
                "id": "crew",
                "name": "Crew",
                "model": {"id": "gpt-5.4", "provider": "OpenAI"},
                "members": [{"type": "agent", "agent_id": "worker"}],
            },
        )
        runner = StudioRunnerTools(registry=registry, db=db)
        assert runner._team_for_run("crew") is not None  # healthy before the fault

        # With a registry present, the reference check is the only reader of a
        # member's stored config, so this fault lands on exactly that read.
        original = runner._load_config_row_from_db

        def failing(component_id, **kwargs):
            if component_id == "worker":
                raise RuntimeError(PRIVATE_RUNTIME_ERROR)
            return original(component_id, **kwargs)

        runner._load_config_row_from_db = failing  # type: ignore[method-assign]
        out = _loads(runner.run_team("crew", "hi"))

        assert out == {"error": "StudioRunnerTools could not resolve team."}
        assert PRIVATE_RUNTIME_ERROR not in json.dumps(out)
        assert PRIVATE_RUNTIME_ERROR not in caplog.text

    def test_reference_stored_under_another_type_is_refused(self, db, registry):
        """A code-defined reference is simply absent from the components table.
        An id that IS there under another type is a contradiction, and whatever
        it resolved to cannot be checked against any stored config."""
        db.upsert_component(component_id="x", component_type="team", name="X-Team")
        db.upsert_config(
            component_id="x",
            stage="published",
            config={"id": "x", "name": "X-Team", "model": {"id": "gpt-5.4", "provider": "OpenAI"}, "members": []},
        )
        db.upsert_component(component_id="flow", component_type="workflow", name="Flow")
        db.upsert_config(
            component_id="flow",
            stage="published",
            config={"id": "flow", "name": "Flow", "steps": [{"name": "s", "agent_id": "x"}]},
        )

        error = _loads(StudioRunnerTools(registry=registry, db=db).run_workflow("flow", "hi"))["error"]
        assert "stores 'x' as a team" in error

    def test_step_executor_is_checked_against_its_own_stored_config(self, db, registry):
        """A workflow's config carries none of the schemas its step executors
        declare, so the top-level fidelity check is silent for a workflow. An
        executor that lost a registry-backed piece must be refused as a step
        exactly as it is refused when dispatched directly."""

        class Report(BaseModel):
            title: str

        db.upsert_component(component_id="shaped", component_type="agent", name="Shaped")
        db.upsert_config(
            component_id="shaped",
            stage="published",
            config={
                "id": "shaped",
                "name": "Shaped",
                "model": {"id": "gpt-5.4", "provider": "OpenAI"},
                "output_schema": "Report",
            },
        )
        db.upsert_component(component_id="flow", component_type="workflow", name="Flow")
        db.upsert_config(
            component_id="flow",
            stage="published",
            config={"id": "flow", "name": "Flow", "steps": [{"name": "s", "agent_id": "shaped"}]},
        )

        thin = StudioRunnerTools(registry=registry, db=db)
        # Naming the lost schema is the contract; the exact wording belongs to
        # whichever layer refuses first.
        assert "Report" in _loads(thin.run_agent("shaped", "hi")).get("error", "")
        assert "Report" in _loads(thin.run_workflow("flow", "hi")).get("error", "")

        # The control matters as much as the refusal: a registry that does hold
        # the schema must still dispatch, or the check is just a wall.
        registry.schemas = [Report]
        whole = StudioRunnerTools(registry=registry, db=db)
        assert whole._agent_for_run("shaped").output_schema is Report
        assert whole._workflow_for_run("flow").steps[0].agent.output_schema is Report

    def test_create_refuses_an_idless_member_or_step(self, registry, db):
        # Typed component refs require a stable non-empty id before Studio can
        # persist either a team member or workflow executor.
        with pytest.raises(ValueError):
            ComponentRef(component_type="agent", component_id="")
        with pytest.raises(ValueError):
            AgentWorkflowStep(kind="agent", name="s1", component_id="")
        assert db.get_component("crew") is None
        assert db.get_component("flow") is None

    def test_edit_team_keeps_agents_list_members_resolvable(self, registry, db):
        # StudioTools mirrors agents_list into the registry so rehydration can
        # see those members: an unrelated edit now succeeds and the stored
        # roster survives, where it previously had to refuse to avoid
        # publishing a silently shrunken version.
        from agno.agent.agent import Agent as AgentClass

        worker = AgentClass(id="worker", name="Worker", model=OpenAIResponses(id="gpt-5.4"))
        studio = _studio(registry, db, teams=True, agents_list=[worker])
        created = _create_team(
            studio,
            _team_request("crew", [ComponentRef(component_type="agent", component_id="worker")]),
            save_as="draft",
        )
        assert created.members == [ComponentRef(component_type="agent", component_id="worker")]

        out = studio.edit_team(
            "crew",
            TeamPatch(instructions="new"),
            expected_version=1,
            _agno_run_context=_context(),
        )
        assert out.ok, out.error
        assert out.data is not None
        assert out.data.members == [ComponentRef(component_type="agent", component_id="worker")]

        # The stored roster is intact and still names the member.
        row = db.get_config(component_id="crew", version=2)
        stored = row.get("config") if isinstance(row, dict) else {}
        assert [m.get("agent_id") for m in (stored or {}).get("members", [])] == ["worker"]

    def test_runner_refuses_team_with_idless_member(self, registry, db):
        # A legacy or externally persisted config can still carry agent_id null
        # (create_team now refuses to write one), and the dispatch guard must
        # refuse it with or without a registry.
        config = {
            "id": "crew",
            "name": "crew",
            "model": {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"},
            "instructions": "i",
            "members": [{"type": "agent", "agent_id": None}],
        }
        db.upsert_component(component_id="crew", component_type="team", name="crew")
        db.upsert_config(component_id="crew", config=config, stage="published")

        # No registry makes a null reference resolvable, so the refusal does
        # not depend on one: a lookup by None matches the first component that
        # also has no id.
        for runner in (StudioRunnerTools(db=db), StudioRunnerTools(registry=registry, db=db)):
            out = _loads(runner.run_team("crew", "hi"))
            assert "had no id when it was saved" in out.get("error", "")
            assert "not found" not in out.get("error", "")

    def test_unrebuildable_db_reference_warns_and_falls_back(self, db):
        # A declared db that neither db_from_dict nor the registry can supply
        # falls back to the catalog db. The component still runs; the fallback
        # is announced rather than silent.
        import logging

        config = {
            "id": "redis-agent",
            "model": {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"},
            "instructions": "i",
            "db": {"type": "redis", "id": "prod-redis"},
        }
        db.upsert_component(component_id="redis-agent", component_type="agent", name="RedisAgent")
        db.upsert_config(component_id="redis-agent", config=config, stage="published")

        records: list = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        logging.getLogger("agno").addHandler(handler)
        try:
            loaded = StudioRunnerTools(db=db)._find_agent("redis-agent")
        finally:
            logging.getLogger("agno").removeHandler(handler)
        assert loaded is not None
        assert loaded.db is db
        assert any("could not be reconstructed" in message for message in records)

    def test_untyped_db_config_still_loads(self, db):
        # Only postgres/sqlite/clickhouse serialize a "type"; every other
        # backend inherits BaseDb.to_dict, which does not. A missing type must
        # not make the component unrunnable.
        config = {
            "id": "plain-db-agent",
            "model": {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"},
            "instructions": "be useful",
            "db": {"id": "runner-test-db"},
        }
        db.upsert_component(component_id="plain-db-agent", component_type="agent", name="PlainDbAgent")
        db.upsert_config(component_id="plain-db-agent", config=config, stage="published")

        loaded = StudioRunnerTools(db=db)._find_agent("plain-db-agent")
        assert loaded is not None
        assert loaded.db is db
        assert loaded.instructions == "be useful"

    def test_db_workflow_step_holding_registry_singleton_refuses_dispatch(self, db):
        # Step.from_dict keeps the shared registry agent when its deep_copy
        # raises. Dispatch refuses it; reads and edits still reach it, so the
        # step can be replaced.
        from agno.agent.agent import Agent as AgentClass

        class _UncopyableAgent(AgentClass):
            def __init__(self, topic, **kwargs):
                self.topic = topic
                super().__init__(**kwargs)

        live_model = OpenAIResponses(id="gpt-5.4")
        researcher = _UncopyableAgent("ai", id="researcher", name="Researcher", model=live_model, db=db)
        reg = Registry(name="Singleton Registry", agents=[researcher], models=[live_model], dbs=[db])
        studio = _studio(reg, db, workflows=True)
        created = _create_workflow(
            studio,
            _workflow_request(
                "Flow",
                [AgentWorkflowStep(kind="agent", name="s1", component_id="researcher")],
            ),
            save_as="draft",
        )
        assert created.stage == "draft"
        db.upsert_config(
            component_id="flow",
            version=1,
            stage="published",
            guard=ComponentVersionGuard(latest_version=1, current_version=None),
        )

        out = _loads(StudioRunnerTools(registry=reg, db=db).run_workflow("flow", "go"))
        assert "shared registry instance" in out.get("error", "")

        # Reads reach the workflow, and no read or edit reports the dispatch
        # refusal, so the offending step stays repairable.
        assert studio.get_workflow("flow", _agno_run_context=_context()).ok
        edited = studio.edit_workflow(
            "flow",
            WorkflowPatch(description="new"),
            expected_version=1,
            _agno_run_context=_context(),
        )
        assert edited.ok, edited.error

    def test_healthy_workflow_step_dispatches(self, registry, db):
        # The isolation check must not refuse a step whose registry agent
        # copies cleanly.
        from agno.agent.agent import Agent as AgentClass

        live_model = OpenAIResponses(id="gpt-5.4")
        researcher = AgentClass(id="researcher", name="Researcher", model=live_model, db=db)
        reg = Registry(name="Healthy Registry", agents=[researcher], models=[live_model], dbs=[db])
        studio = _studio(reg, db, workflows=True)
        _create_workflow(
            studio,
            _workflow_request(
                "Flow",
                [AgentWorkflowStep(kind="agent", name="s1", component_id="researcher")],
            ),
            save_as="draft",
        )
        db.upsert_config(
            component_id="flow",
            version=1,
            stage="published",
            guard=ComponentVersionGuard(latest_version=1, current_version=None),
        )

        loaded = StudioRunnerTools(registry=reg, db=db)._workflow_for_run("flow")
        assert loaded is not None
        assert loaded.steps[0].agent is not researcher

    def test_legacy_model_rebuild_warning_fires_on_dispatch_without_registry(self, registry, db):
        # Legacy configs retain the warning-only behavior. Typed Studio configs
        # are covered below and fail closed instead. Reads stay quiet.
        import logging

        db.upsert_component(component_id="plain", component_type="agent", name="Plain")
        db.upsert_config(
            component_id="plain",
            stage="published",
            config={
                "id": "plain",
                "name": "Plain",
                "instructions": "hi",
                "model": {"id": "gpt-5.4", "provider": "OpenAI", "name": "OpenAIResponses"},
            },
        )

        records: list = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())

        logging.getLogger("agno").addHandler(handler)
        try:
            dispatched = StudioRunnerTools(db=db)._agent_for_run("plain")
        finally:
            logging.getLogger("agno").removeHandler(handler)
        assert dispatched is not None
        assert any("rebuilt from its stored config" in message for message in records)

        # A read does not dispatch, so it does not warn.
        records.clear()
        logging.getLogger("agno").addHandler(handler)
        try:
            StudioRunnerTools(db=db)._find_agent("plain")
        finally:
            logging.getLogger("agno").removeHandler(handler)
        assert not any("rebuilt from its stored config" in message for message in records)

        # The registry instance dispatches silently.
        records.clear()
        logging.getLogger("agno").addHandler(handler)
        try:
            StudioRunnerTools(registry=registry, db=db)._agent_for_run("plain")
        finally:
            logging.getLogger("agno").removeHandler(handler)
        assert not any("rebuilt from its stored config" in message for message in records)

    def test_typed_agent_requires_registry_before_any_model_call(self, db, monkeypatch):
        private_model = OpenAIResponses(
            id="private-model",
            base_url="https://private-model.invalid/v1",
            api_key="private-key",
        )
        full = Registry(name="Full", models=[private_model], dbs=[db])
        studio = _studio(full, db)
        _create_agent(
            studio,
            AgentCreate(
                component_id="private-agent",
                name="Private Agent",
                instructions="Use the private endpoint",
                model=ModelRef(id="private-model", provider="OpenAI", name="OpenAIResponses"),
            ),
        )

        stored = db.get_config("private-agent")
        assert stored is not None
        assert stored["config"]["model"] == {
            "id": "private-model",
            "provider": "OpenAI",
            "name": "OpenAIResponses",
        }

        network_calls: List[str] = []

        def fail_network(*_args: Any, **_kwargs: Any) -> None:
            network_calls.append("invoke")
            raise AssertionError("model network path must not be reached")

        monkeypatch.setattr(OpenAIResponses, "invoke", fail_network)
        error = _loads(StudioRunnerTools(db=db).run_agent("private-agent", "hi"))["error"]

        assert "typed Studio" in error
        assert "registry" in error
        assert network_calls == []

    def test_typed_agent_refuses_a_rebuilt_model_from_an_incomplete_registry(self, db, monkeypatch):
        private_model = OpenAIResponses(
            id="private-model",
            base_url="https://private-model.invalid/v1",
            api_key="private-key",
        )
        full = Registry(name="Full", models=[private_model], dbs=[db])
        _create_agent(
            _studio(full, db),
            AgentCreate(
                component_id="private-agent",
                name="Private Agent",
                instructions="Use the private endpoint",
                model=ModelRef(id="private-model", provider="OpenAI", name="OpenAIResponses"),
            ),
        )
        incomplete = Registry(name="Incomplete", models=[OpenAIResponses(id="another-model")], dbs=[db])

        network_calls: List[str] = []

        def fail_network(*_args: Any, **_kwargs: Any) -> None:
            network_calls.append("invoke")
            raise AssertionError("model network path must not be reached")

        monkeypatch.setattr(OpenAIResponses, "invoke", fail_network)
        error = _loads(StudioRunnerTools(registry=incomplete, db=db).run_agent("private-agent", "hi"))["error"]

        assert "private-model" in error
        assert "registry.models" in error
        assert "base_url" in error
        assert network_calls == []

    def test_typed_team_and_workflow_require_registered_nested_models(self, db, monkeypatch):
        coordinator_model = OpenAIResponses(id="gpt-5.4")
        private_model = OpenAIResponses(
            id="private-model",
            base_url="https://private-model.invalid/v1",
            api_key="private-key",
        )
        full = Registry(name="Full", models=[coordinator_model, private_model], dbs=[db])
        studio = _studio(full, db, teams=True, workflows=True)
        _create_agent(
            studio,
            AgentCreate(
                component_id="private-agent",
                name="Private Agent",
                instructions="Use the private endpoint",
                model=ModelRef(id="private-model", provider="OpenAI", name="OpenAIResponses"),
            ),
        )
        _create_team(
            studio,
            _team_request(
                "Crew",
                [ComponentRef(component_type="agent", component_id="private-agent")],
            ),
        )
        _create_workflow(
            studio,
            _workflow_request(
                "Flow",
                [AgentWorkflowStep(kind="agent", name="private-step", component_id="private-agent")],
            ),
        )

        incomplete = Registry(name="Incomplete", models=[coordinator_model], dbs=[db])
        network_calls: List[str] = []

        def fail_network(*_args: Any, **_kwargs: Any) -> None:
            network_calls.append("invoke")
            raise AssertionError("model network path must not be reached")

        monkeypatch.setattr(OpenAIResponses, "invoke", fail_network)
        runner = StudioRunnerTools(registry=incomplete, db=db)
        team_error = _loads(runner.run_team("crew", "hi"))["error"]
        workflow_error = _loads(runner.run_workflow("flow", "hi"))["error"]

        for error in (team_error, workflow_error):
            assert "private-agent" in error
            assert "private-model" in error
            assert "registry.models" in error
        assert network_calls == []

    def test_code_defined_custom_model_keeps_existing_runner_behavior(self, db):
        stub = _StubAgent()
        stub.model = OpenAIResponses(
            id="code-model",
            base_url="https://code-model.invalid/v1",
            api_key="code-key",
        )

        result = _loads(StudioRunnerTools(db=db, agents_list=[stub]).run_agent("stub", "hi"))

        assert result["status"] == "COMPLETED"
        assert stub.seen is not None

    def test_studio_run_methods_preserve_runner_payload(self, registry, db):
        stub = _StubAgent()
        studio = _studio(registry, db, agents_list=[stub])
        payload = _loads(studio.run_agent("stub", "hi", _agno_run_context=_context()))
        assert payload["agent_id"] == "stub"
        assert "id" not in payload

        error = _loads(studio.run_agent("no-such-agent", "hi", _agno_run_context=_context()))
        assert "error" in error and "id" not in error

    def test_create_team_uses_exact_typed_member_ref(self, registry, db):
        studio = _studio(registry, db, teams=True)
        _create_agent(studio, _agent_request("Radar Scout", component_id="radar-a"))
        _create_agent(studio, _agent_request("Radar Scout", component_id="radar-b"))
        created = _create_team(
            studio,
            _team_request("squad", [ComponentRef(component_type="agent", component_id="radar-b")]),
        )
        assert created.members == [ComponentRef(component_type="agent", component_id="radar-b", version=1)]

    def test_archive_requires_exact_component_id(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout"))
        missing = studio.archive_agent("Radar Scout", expected_current_version=1, _agno_run_context=_context())
        assert missing.error is not None and missing.error.code == "invalid_component_id"
        archived = studio.archive_agent("radar-scout", expected_current_version=1, _agno_run_context=_context())
        assert archived.ok and archived.status == "archived"

    def test_edit_reaches_db_component_shadowed_by_code_defined_name(self, registry, db):
        # A code-defined component NAMED like a DB component's id must not make
        # the DB component uneditable: exact ids win on every path.
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("support"))
        shadow = _StubAgent()
        shadow.id = "code-1"
        shadow.name = "support"
        shadowed = _studio(registry, db, agents_list=[shadow])
        got = _data(shadowed.get_agent("support", _agno_run_context=_context()))
        assert got.component_id == "support"
        out = shadowed.edit_agent(
            "support",
            AgentPatch(instructions="updated"),
            expected_version=1,
            save_as="published",
            _agno_run_context=_context(),
        )
        assert out.ok and out.status == "edited"
        assert out.data is not None and out.data.component_id == "support"

    def test_exact_id_edits_accumulate_drafts_with_expected_version(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Radar Scout", instructions="original"))
        first = studio.edit_agent(
            "radar-scout",
            AgentPatch(instructions="first-change"),
            expected_version=1,
            _agno_run_context=_context(),
        )
        assert first.ok and first.status == "edited"
        second = studio.edit_agent(
            "radar-scout",
            AgentPatch(description="second-change"),
            expected_version=2,
            _agno_run_context=_context(),
        )
        assert second.ok and second.status == "edited"

        configs = db.list_configs("radar-scout", include_config=True)
        drafts = [c for c in configs if c.get("stage") == "draft"]
        latest = max(drafts, key=lambda c: c["version"])
        assert latest["config"]["instructions"] == "first-change"
        assert latest["config"]["description"] == "second-change"

    def test_dispatch_uses_the_current_publication_not_the_latest_draft(self, registry, db):
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Dispatch target", instructions="published"))
        edited = studio.edit_agent(
            "dispatch-target",
            AgentPatch(instructions="draft-only"),
            expected_version=1,
            _agno_run_context=_context(),
        )
        assert edited.ok and edited.data is not None and edited.data.stage == "draft"

        loaded = StudioRunnerTools(registry=registry, db=db)._agent_for_run("dispatch-target")

        assert loaded is not None
        assert loaded.instructions == "published"

    def test_studio_instructions_carry_run_guidance(self, registry, db):
        studio = _studio(registry, db)
        instructions = studio.instructions or ""
        assert "current published version" in instructions
        assert "exact typed references" in instructions.lower()


class TestTypedRegistryExactness:
    def test_dispatch_refuses_an_ambiguous_exact_model_reference(self, db):
        intended = OpenAIResponses(
            id="private-model",
            base_url="https://intended-model.invalid/v1",
            api_key="intended-secret",
        )
        initial_registry = Registry(name="initial", models=[intended], dbs=[db])
        studio = _studio(initial_registry, db)
        _create_agent(
            studio,
            AgentCreate(
                component_id="model-bound-agent",
                name="Model bound agent",
                instructions="Use the exact private model.",
                model=ModelRef(id="private-model", provider=intended.provider, name=intended.name),
            ),
        )
        wrong = OpenAIResponses(
            id="private-model",
            base_url="https://wrong-model.invalid/v1",
            api_key="wrong-secret",
        )
        ambiguous_registry = Registry(name="ambiguous", models=[wrong, intended], dbs=[db])

        with pytest.raises(ComponentNeedsRegistryError, match="model reference.*ambiguous") as error:
            StudioRunnerTools(registry=ambiguous_registry, db=db)._agent_for_run("model-bound-agent")

        assert "wrong-model.invalid" not in str(error.value)
        assert "wrong-secret" not in str(error.value)

    def test_dispatch_refuses_an_ambiguous_exact_tool_reference(self, db):
        model = OpenAIResponses(id="gpt-5.4")

        def intended_lookup(query: str) -> str:
            return f"intended: {query}"

        def wrong_lookup(query: str) -> str:
            return f"wrong: {query}"

        intended_lookup.__name__ = "lookup"
        wrong_lookup.__name__ = "lookup"
        initial_registry = Registry(name="initial", tools=[intended_lookup], models=[model], dbs=[db])
        studio = _studio(initial_registry, db)
        _create_agent(
            studio,
            _agent_request(
                "Tool bound agent",
                component_id="tool-bound-agent",
                tools=[ToolRef(kind="function", name="lookup")],
            ),
        )
        ambiguous_registry = Registry(
            name="ambiguous",
            tools=[intended_lookup, wrong_lookup],
            models=[model],
            dbs=[db],
        )

        with pytest.raises(ComponentNeedsRegistryError, match="tool reference.*ambiguous"):
            StudioRunnerTools(registry=ambiguous_registry, db=db)._agent_for_run("tool-bound-agent")

    def test_dispatch_refuses_when_a_toolkit_member_shadows_a_direct_function(self, db):
        from agno.tools.toolkit import Toolkit

        model = OpenAIResponses(id="gpt-5.4")

        def intended_lookup(query: str) -> str:
            return f"intended: {query}"

        def wrong_lookup(query: str) -> str:
            return f"wrong: {query}"

        intended_lookup.__name__ = "lookup"
        wrong_lookup.__name__ = "lookup"
        wrong_toolkit = Toolkit(name="wrongkit", tools=[wrong_lookup])
        initial_registry = Registry(
            name="initial",
            tools=[intended_lookup],
            models=[model],
            dbs=[db],
        )
        studio = _studio(initial_registry, db)
        _create_agent(
            studio,
            _agent_request(
                "Shadowed tool agent",
                component_id="shadowed-tool-agent",
                tools=[ToolRef(kind="function", name="lookup")],
            ),
        )

        shadowed_registry = Registry(
            name="shadowed",
            tools=[intended_lookup, wrong_toolkit],
            models=[model],
            dbs=[db],
        )

        with pytest.raises(ComponentNeedsRegistryError, match="runtime binding.*diverges"):
            StudioRunnerTools(registry=shadowed_registry, db=db)._agent_for_run("shadowed-tool-agent")

    def test_same_entrypoint_registered_directly_and_in_a_toolkit_is_safe(self, db):
        from agno.tools.toolkit import Toolkit

        model = OpenAIResponses(id="gpt-5.4")

        def lookup(query: str) -> str:
            return f"same: {query}"

        registry = Registry(
            name="same behavior",
            tools=[lookup, Toolkit(name="samekit", tools=[lookup])],
            models=[model],
            dbs=[db],
        )
        studio = _studio(registry, db)
        _create_agent(
            studio,
            _agent_request(
                "Same behavior agent",
                component_id="same-behavior-agent",
                tools=[ToolRef(kind="function", name="lookup")],
            ),
        )

        loaded = StudioRunnerTools(registry=registry, db=db)._agent_for_run("same-behavior-agent")
        assert loaded is not None

    def test_dispatch_refuses_an_ambiguous_workflow_function_reference(self, db):
        def intended_execute(value: str) -> str:
            return f"intended: {value}"

        def wrong_execute(value: str) -> str:
            return f"wrong: {value}"

        intended_execute.__name__ = "execute"
        wrong_execute.__name__ = "execute"
        initial_registry = Registry(name="initial", functions=[intended_execute], dbs=[db])
        studio = _studio(initial_registry, db, workflows=True)
        _create_workflow(
            studio,
            WorkflowCreate(
                component_id="function-bound-workflow",
                name="Function bound workflow",
                steps=[
                    FunctionWorkflowStep(
                        kind="function",
                        step_id="execute-step",
                        name="Execute",
                        function_name="execute",
                    )
                ],
            ),
        )
        ambiguous_registry = Registry(
            name="ambiguous",
            functions=[wrong_execute, intended_execute],
            dbs=[db],
        )

        with pytest.raises(ComponentNeedsRegistryError, match="function reference.*ambiguous"):
            StudioRunnerTools(registry=ambiguous_registry, db=db)._workflow_for_run("function-bound-workflow")


class TestDispatchCheckInvariants:
    """Properties every dispatch check has to share.

    Four review rounds found the same shape each time: a rule applied to the
    one place it was reported and not to its siblings. These assert the class,
    so the next sibling cannot be missed quietly."""

    def _walkers(self):
        import inspect

        from agno.tools import studio_runner as module

        return inspect.getsource(module)

    def test_every_graph_walk_shares_one_depth_bound(self):
        # A walk that stops earlier than the gate that admitted the graph
        # reports "nothing wrong" for a graph it never finished reading.
        source = self._walkers()
        assert "depth > 12" not in source, "a walk still carries its own depth bound"
        assert source.count("_GRAPH_MAX_DEPTH") >= 6
        assert source.count("_GRAPH_MAX_NODES") >= 3

    def test_the_depth_bound_refuses_rather_than_returns(self, db):
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.team import Team

        node: Any = Agent(id="leaf", name="Leaf", model=OpenAIResponses(id="gpt-5.4"))
        for index in range(40):
            node = Team(id=f"t{index}", name=f"t{index}", model=OpenAIResponses(id="gpt-5.4"), members=[node])
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, teams_list=[node])
        assert "nests deeper than" in _loads(runner.run_team(node.id, "hi"))["error"]

    def test_the_node_bound_refuses_rather_than_silently_skipping_wide_siblings(
        self, db, monkeypatch: pytest.MonkeyPatch
    ):
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.team import Team
        from agno.tools import studio_runner as module

        members = [
            Agent(id=f"member-{index}", name=f"Member {index}", model=OpenAIResponses(id="gpt-5.4"))
            for index in range(4)
        ]
        team = Team(id="wide-team", name="Wide team", model=OpenAIResponses(id="gpt-5.4"), members=members)
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, teams_list=[team])
        monkeypatch.setattr(module, "_GRAPH_MAX_NODES", 4)

        result = _loads(runner.run_team("wide-team", "hi"))

        assert "more than 4 inspectable graph nodes" in result["error"]

    def test_shared_member_search_reaches_past_the_old_bound(self):
        from agno.agent import Agent
        from agno.team import Team

        leaf = Agent(id="leaf", name="Leaf", model=OpenAIResponses(id="gpt-5.4"))
        node: Any = Team(id="t0", name="t0", model=OpenAIResponses(id="gpt-5.4"), members=[leaf])
        for index in range(1, 20):
            node = Team(id=f"t{index}", name=f"t{index}", model=OpenAIResponses(id="gpt-5.4"), members=[node])
        assert StudioRunnerTools._shared_registry_instance(node, [leaf]) is leaf

    def test_every_id_map_carries_the_component_type(self):
        # Ids are unique per type only, so an agent and a team may share one.
        from agno.agent import Agent
        from agno.team import Team

        agent = Agent(id="dup", name="AnAgent", model=OpenAIResponses(id="gpt-5.4"))
        team = Team(id="dup", name="ATeam", model=OpenAIResponses(id="gpt-5.4"), members=[agent])
        holder = Team(id="holder", name="holder", model=OpenAIResponses(id="gpt-5.4"), members=[team])
        by_id = StudioRunnerTools._components_by_id(holder)
        assert ("team", "dup") in by_id and ("agent", "dup") in by_id
        assert by_id[("team", "dup")] is team and by_id[("agent", "dup")] is agent

    def test_a_copy_that_changed_behaviour_is_not_faithful(self):
        # Identity is not just the label: a copy answering from another model,
        # under other instructions, or without the tools it had is a different
        # component wearing the right name.
        from agno.agent import Agent
        from agno.tools.calculator import CalculatorTools

        def agent(model_id="gpt-5.4", instructions="ORIGINAL", with_tools=True):
            built = Agent(id="x", name="X", model=OpenAIResponses(id=model_id), instructions=instructions)
            if with_tools:
                built.tools = [CalculatorTools()]
            return built

        original = agent()
        # One dimension differs at a time, so each is asserted on its own
        # rather than riding on another's refusal.
        assert StudioRunnerTools._copy_lost_identity(original, agent(model_id="gpt-4o-mini"))
        assert StudioRunnerTools._copy_lost_identity(original, agent(instructions="REWRITTEN"))
        assert StudioRunnerTools._copy_lost_identity(original, agent(with_tools=False))
        assert not StudioRunnerTools._copy_lost_identity(original, agent())

    def test_the_same_tools_in_another_shape_are_still_the_same_reach(self):
        # A toolkit here and its expanded functions there are one set of tools.
        # Comparing the objects would call a healthy copy degraded, which is
        # the false refusal this check has to avoid.
        from agno.agent import Agent
        from agno.tools.calculator import CalculatorTools
        from agno.tools.function import Function

        toolkit = CalculatorTools()
        held_as_toolkit = Agent(id="x", name="X", model=OpenAIResponses(id="gpt-5.4"), tools=[toolkit])
        held_as_functions = Agent(id="x", name="X", model=OpenAIResponses(id="gpt-5.4"))
        held_as_functions.tools = [Function(name=name) for name in toolkit.functions]
        assert not StudioRunnerTools._copy_lost_identity(held_as_toolkit, held_as_functions)

    def test_a_callable_factory_is_reported_rather_than_silently_skipped(self, db, caplog):
        # members=/tools=/steps= accept a factory the framework resolves per run,
        # so there is nothing to inspect at dispatch and the per-run-copy promise
        # does not reach what it returns. Supported, so not refused -- but said.
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.team import Team

        member = Agent(id="m", name="M", model=OpenAIResponses(id="gpt-5.4"))
        lazy = Team(id="lazy", name="Lazy", model=OpenAIResponses(id="gpt-5.4"), members=lambda: [member])
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, teams_list=[lazy])

        with caplog.at_level("WARNING"):
            assert runner._team_for_run("lazy") is not None
        assert any("callable members factory" in record.message for record in caplog.records)

    def test_a_member_is_judged_by_the_rule_a_step_executor_is(self):
        # _member_divergence answered only type/id/name while the executor path
        # asked _copy_lost_identity, so a member could come back stripped of its
        # model and instructions and still read as the member that was asked for.
        from agno.agent import Agent
        from agno.team import Team

        def team_with(member):
            return Team(id="t", name="T", model=OpenAIResponses(id="gpt-5.4"), members=[member])

        original = team_with(Agent(id="m", name="M", model=OpenAIResponses(id="gpt-5.4"), instructions="RULES"))
        degraded = team_with(Agent(id="m", name="M", model=None, instructions=None))
        assert StudioRunnerTools._member_divergence(original, degraded) is not None

        faithful = team_with(Agent(id="m", name="M", model=OpenAIResponses(id="gpt-5.4"), instructions="RULES"))
        assert StudioRunnerTools._member_divergence(original, faithful) is None

    def test_a_wide_graph_is_checked_as_far_as_a_narrow_one(self, db, registry):
        # The reference walk bounded itself by how many components it had seen,
        # which is a breadth counter: a team with more members than the cap
        # stopped checking the rest of them, and the loss below the last member
        # was never reached.
        def store(component_id, component_type, config):
            db.upsert_component(component_id=component_id, component_type=component_type, name=component_id)
            db.upsert_config(component_id=component_id, config=config, stage="published")

        model_config = {"id": "gpt-5.4", "provider": "OpenAI"}
        for index in range(40):
            store(f"a{index}", "agent", {"id": f"a{index}", "name": f"a{index}", "model": model_config})
        store("hidden", "agent", {"id": "hidden", "name": "hidden", "model": model_config, "output_schema": "Report"})
        store(
            "sub",
            "team",
            {"id": "sub", "name": "sub", "model": model_config, "members": [{"type": "agent", "agent_id": "hidden"}]},
        )
        wide = [{"type": "agent", "agent_id": f"a{index}"} for index in range(40)]
        store(
            "wide",
            "team",
            {
                "id": "wide",
                "name": "wide",
                "model": model_config,
                "members": wide + [{"type": "team", "team_id": "sub"}],
            },
        )
        store(
            "narrow",
            "team",
            {
                "id": "narrow",
                "name": "narrow",
                "model": model_config,
                "members": [{"type": "agent", "agent_id": "a0"}, {"type": "team", "team_id": "sub"}],
            },
        )

        runner = StudioRunnerTools(registry=registry, db=db)
        # The same nested loss, once behind 40 siblings and once behind one.
        assert "Report" in _loads(runner.run_team("narrow", "hi"))["error"]
        assert "Report" in _loads(runner.run_team("wide", "hi"))["error"]

    def test_a_registered_id_only_excuses_the_type_that_registered_it(self, db, registry):
        # A reference resolved from the registry is not judged against a stored
        # config it was never built from. Keyed by bare id, an agent named 'dup'
        # excused a stored TEAM called 'dup' from being checked at all.
        from agno.agent import Agent

        registry.agents = [Agent(id="dup", name="RegisteredAgent", model=OpenAIResponses(id="gpt-5.4"))]
        model_config = {"id": "gpt-5.4", "provider": "OpenAI"}
        for component_id, component_type, config in (
            ("inner", "agent", {"id": "inner", "name": "inner", "model": model_config, "output_schema": "Report"}),
            (
                "dup",
                "team",
                {
                    "id": "dup",
                    "name": "DupTeam",
                    "model": model_config,
                    "members": [{"type": "agent", "agent_id": "inner"}],
                },
            ),
            (
                "outer",
                "team",
                {
                    "id": "outer",
                    "name": "outer",
                    "model": model_config,
                    "members": [{"type": "team", "team_id": "dup"}],
                },
            ),
        ):
            db.upsert_component(component_id=component_id, component_type=component_type, name=component_id)
            db.upsert_config(component_id=component_id, config=config, stage="published")

        assert "Report" in _loads(StudioRunnerTools(registry=registry, db=db).run_team("outer", "hi"))["error"]

    def test_a_tool_bound_from_another_toolkit_is_refused(self, db):
        """A serialized tool carries the toolkit that owned it. When that
        toolkit is gone, rehydration binds a same-named function from a
        different one and keeps the recorded owning_toolkit, so the component
        executes someone else's code under the right name. Same-named members
        are ordinary -- search, lookup, run -- so this is not an exotic case."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.tools.toolkit import Toolkit

        class Alpha(Toolkit):
            def __init__(self):
                super().__init__(name="alpha_tools", tools=[self.lookup])

            def lookup(self) -> str:
                """Look up."""
                return "ALPHA"

        class Beta(Toolkit):
            def __init__(self):
                super().__init__(name="beta_tools", tools=[self.lookup])

            def lookup(self) -> str:
                """Look up."""
                return "BETA"

        Agent(id="tooled", name="Tooled", model=OpenAIResponses(id="gpt-5.4"), tools=[Alpha()]).save(db=db)

        substitute = Registry(name="R", dbs=[db], models=[OpenAIResponses(id="gpt-5.4")], tools=[Beta()])
        error = _loads(StudioRunnerTools(registry=substitute, db=db).run_agent("tooled", "hi"))["error"]
        assert "another toolkit" in error and "alpha_tools.lookup" in error

        # The toolkit that was recorded still dispatches, and runs its own code.
        intact = Registry(name="R", dbs=[db], models=[OpenAIResponses(id="gpt-5.4")], tools=[Alpha()])
        dispatched = StudioRunnerTools(registry=intact, db=db)._agent_for_run("tooled")
        assert dispatched is not None
        assert dispatched.tools[0].entrypoint() == "ALPHA"

    def test_a_resolved_db_that_routes_elsewhere_is_refused(self, db, registry, tmp_path, caplog):
        """A stored db is rebuilt from its own config, resolved from the
        registry by id, or replaced by the catalog db -- and only the first
        applies the table overrides the component declared. A registry instance
        is used as it was registered, so a component asking for isolated tables
        can be dispatched onto shared ones. Checked against the db the
        component actually holds, for every component type."""
        from agno.db.json import JsonDb

        registered = JsonDb(id="tenant-json", db_path=str(tmp_path / "tenant"), session_table="shared_sessions")
        registry.dbs = [db, registered]
        model_config = {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"}
        routing = {"id": "tenant-json", "session_table": "isolated_sessions"}
        for component_id, component_type, extra in (
            ("a1", "agent", {}),
            ("t1", "team", {"members": [{"type": "agent", "agent_id": "a1"}]}),
            ("w1", "workflow", {"steps": [{"name": "s", "agent_id": "a1"}]}),
        ):
            config = {"id": component_id, "name": component_id, "model": model_config, "db": dict(routing)}
            config.update(extra)
            db.upsert_component(component_id=component_id, component_type=component_type, name=component_id)
            db.upsert_config(component_id=component_id, config=config, stage="published")

        runner = StudioRunnerTools(registry=registry, db=db)
        assert "routes differently" in _loads(runner.run_agent("a1", "hi"))["error"]
        assert "routes differently" in _loads(runner.run_team("t1", "hi"))["error"]
        assert "routes differently" in _loads(runner.run_workflow("w1", "hi"))["error"]

        # Registered as declared, so nothing is redirected and it runs.
        registry.dbs = [db, JsonDb(id="tenant-json", db_path=str(tmp_path / "ok"), session_table="isolated_sessions")]
        assert StudioRunnerTools(registry=registry, db=db)._agent_for_run("a1") is not None

    def test_a_declared_db_that_resolves_to_nothing_is_refused(self, db, registry):
        """Comparing a declared db against an absent one finds no differing
        keys, so the loudest mismatch read as a match. A referenced member or
        step executor is what reaches this: the loaders hand the dispatched
        component the catalog db, and nothing backfills a nested one."""
        model_config = {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"}
        for component_id, component_type, extra in (
            ("member", "agent", {"db": {"type": "redis", "id": "ghost-db"}}),
            ("crew", "team", {"members": [{"type": "agent", "agent_id": "member"}]}),
            ("flow", "workflow", {"steps": [{"name": "s", "agent_id": "member"}]}),
        ):
            config = {"id": component_id, "name": component_id, "model": model_config}
            config.update(extra)
            db.upsert_component(component_id=component_id, component_type=component_type, name=component_id)
            db.upsert_config(component_id=component_id, config=config, stage="published")

        runner = StudioRunnerTools(registry=registry, db=db)
        for component_id, tool in (("crew", runner.run_team), ("flow", runner.run_workflow)):
            error = _loads(tool(component_id, "hi")).get("error", "")
            # On this branch member hydration backfills the caller db, so the
            # walk can see the ghost declaration as a redirection instead of a
            # void. Either way the dispatch refuses and names the member.
            assert "no db resolved" in error or "routes differently" in error, component_id
            assert "member" in error, component_id

    def test_branch_pins_pair_each_occurrence_with_its_own_config(self, db, registry):
        """Two branches pin the same child id at different versions. The walk
        must pair each rebuilt branch object with the config version its own
        branch-qualified link pinned: collapsed by id, the v1 branch (which
        declares a reasoning model nothing reconstructs) was validated against
        the v2 config and dispatched degraded."""
        from agno.agent import Agent
        from agno.workflow.condition import Condition
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        model = OpenAIResponses(id="gpt-5.4")
        rich = Agent(id="shared-agent", name="A", model=model, reasoning_model=OpenAIResponses(id="gpt-5.5"))
        plain = Agent(id="shared-agent", name="A", model=model)
        Workflow(
            id="branch-workflow",
            name="Branch workflow",
            steps=[
                Condition(
                    name="branch",
                    evaluator=True,
                    steps=[Step(step_id="aaa-rich", name="rich", agent=rich)],
                    else_steps=[Step(step_id="zzz-plain", name="plain", agent=plain)],
                )
            ],
        ).save(db=db)

        runner = StudioRunnerTools(registry=registry, db=db)
        error = _loads(runner.run_workflow("branch-workflow", "hi")).get("error", "")
        assert "reasoning_model" in error
        assert "shared-agent" in error

    def test_branch_pins_catch_a_redirected_db_before_any_write(self, db, registry, tmp_path):
        """The isolated branch's agent declares tenant tables the registry's
        shared instance does not route to. Collapsed by id, only the shared
        occurrence was compared, the dispatch completed and the isolated
        branch's session landed in the shared table."""
        from agno.agent import Agent
        from agno.db.json import JsonDb
        from agno.workflow.condition import Condition
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        isolated = JsonDb(id="tenant-json", db_path=str(tmp_path / "isolated"), session_table="isolated_sessions")
        shared = JsonDb(id="tenant-json", db_path=str(tmp_path / "shared"), session_table="shared_sessions")
        registry.dbs = [db, shared]
        model = OpenAIResponses(id="gpt-5.4")
        Workflow(
            id="tenant-workflow",
            name="Tenant workflow",
            steps=[
                Condition(
                    name="branch",
                    evaluator=True,
                    steps=[
                        Step(
                            step_id="aaa-isolated",
                            name="isolated",
                            agent=Agent(id="tenant-agent", name="A", model=model, db=isolated),
                        )
                    ],
                    else_steps=[
                        Step(
                            step_id="zzz-shared",
                            name="shared",
                            agent=Agent(id="tenant-agent", name="A", model=model, db=shared),
                        )
                    ],
                )
            ],
        ).save(db=db)

        runner = StudioRunnerTools(registry=registry, db=db)
        error = _loads(runner.run_workflow("tenant-workflow", "hi")).get("error", "")
        assert "routes differently" in error and "session_table" in error
        assert shared.get_sessions() in ([], ([], 0))
        assert isolated.get_sessions() in ([], ([], 0))

    def test_a_code_only_allowlist_is_listable_without_a_database(self):
        """An allowlist runs without a database, so it has to be findable
        without one: the caller is told to list first and run by id."""
        from agno.agent import Agent
        from agno.registry import Registry

        coded = Agent(id="helper", name="Helper", model=OpenAIResponses(id="gpt-5.4"))
        runner = StudioRunnerTools(registry=Registry(name="R"), agents_list=[coded])

        listing = _loads(runner.list_agents())
        assert listing["agents"] == [{"id": "helper", "name": "Helper", "description": None}]
        assert runner._agent_for_run("helper") is not None

        # With nothing admitted and no database there is genuinely nothing to
        # report, and saying so beats an empty list.
        assert "error" in _loads(StudioRunnerTools(registry=Registry(name="R")).list_agents())

    def test_a_legacy_edit_refuses_without_deleting_unrestored_config(self, db, registry):
        """The typed control plane does not guess how to edit a legacy config.

        Refusing the unsupported manifest leaves declarations that from_dict
        cannot restore untouched, so an unrelated edit cannot quietly lift the
        runner's dispatch refusal.
        """
        from agno.agent import Agent

        Agent(
            id="rich",
            name="Rich",
            model=OpenAIResponses(id="gpt-5.4"),
            reasoning_model=OpenAIResponses(id="o3-deep"),
        ).save(db=db)

        runner = StudioRunnerTools(registry=registry, db=db)
        assert "reasoning_model" in _loads(runner.run_agent("rich", "hi"))["error"]

        studio = _studio(registry, db)
        result = studio.edit_agent(
            "rich",
            AgentPatch(description="an unrelated change"),
            expected_version=1,
            save_as="published",
            _agno_run_context=_context(),
        )

        assert result.error is not None and result.error.code == "unsupported_component_config"

        stored = db.get_config(component_id="rich") or {}
        assert (stored.get("config") or {}).get("reasoning_model") is not None
        assert len(db.list_configs("rich", include_config=True)) == 1
        assert "reasoning_model" in _loads(runner.run_agent("rich", "hi"))["error"]

    def test_an_edit_refuses_rather_than_guessing_when_it_cannot_read_the_original(self, db, registry, monkeypatch):
        """A read that fails is not evidence there was nothing to carry. Taking
        it as an empty set publishes an edit that deletes the declaration and
        lifts the refusal it causes, so the failure has to reach the caller."""
        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Rich", component_id="rich"))
        original = db.get_config
        before = original(component_id="rich")

        def failing(component_id, **kwargs):
            if component_id == "rich":
                raise RuntimeError("transient db failure")
            return original(component_id, **kwargs)

        monkeypatch.setattr(db, "get_config", failing)
        result = studio.edit_agent(
            "rich",
            AgentPatch(description="an unrelated change"),
            expected_version=1,
            save_as="published",
            _agno_run_context=_context(),
        )

        assert result.error is not None and result.error.code == "internal_error"
        assert original(component_id="rich") == before
        assert len(db.list_configs("rich", include_config=True)) == 1

    def test_a_teams_reasoning_model_survives_being_saved(self, db, registry):
        """It was dropped at save time, so the loader had nothing to notice and
        the team dispatched without the reasoning it was configured for -- the
        exact different-pipeline outcome the refusal exists to prevent. Nothing
        reads it back yet (#9452), but losing it before anything can is a
        separate loss."""
        from agno.agent import Agent
        from agno.team import Team

        Team(
            id="crew",
            name="Crew",
            model=OpenAIResponses(id="gpt-5.4"),
            members=[Agent(id="m", name="M", model=OpenAIResponses(id="gpt-5.4"))],
            reasoning_model=OpenAIResponses(id="o3-deep"),
        ).save(db=db)

        stored = (db.get_config(component_id="crew") or {}).get("config") or {}
        assert stored.get("reasoning_model") is not None
        assert "reasoning_model" in _loads(StudioRunnerTools(registry=registry, db=db).run_team("crew", "hi"))["error"]

        # A team that declares none is untouched.
        Team(
            id="plain",
            name="Plain",
            model=OpenAIResponses(id="gpt-5.4"),
            members=[Agent(id="m2", name="M2", model=OpenAIResponses(id="gpt-5.4"))],
        ).save(db=db)
        assert StudioRunnerTools(registry=registry, db=db)._team_for_run("plain") is not None

    def test_a_name_cannot_reach_a_component_its_id_shadows(self, db, registry):
        """An exact id resolves to the code component and the listing shows
        only that one, so letting the display name reach the stored component
        behind it makes one id mean two things depending on spelling -- and
        runs something that was never discoverable."""
        from agno.agent import Agent

        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("Database Target"))
        runner = StudioRunnerTools(
            registry=registry,
            db=db,
            agents_list=[Agent(id="database-target", name="Code Target", model=OpenAIResponses(id="gpt-5.4"))],
        )

        assert "names the stored agent" in _loads(runner.run_agent("Database Target", "hi"))["error"]
        # The id runs the component the listing advertises...
        assert runner._agent_for_run("database-target").name == "Code Target"
        # ...and reads still reach the stored one, which is how it gets fixed.
        assert runner._find_agent("Database Target").name == "Database Target"

        # An unshadowed name is untouched.
        _create_agent(studio, _agent_request("Solo"))
        assert runner._agent_for_run("Solo") is not None

    def test_total_counts_a_shadowed_row_beyond_the_page(self, db, registry):
        """The overlap is counted against the whole table: a shadowed row past
        the cap is still one component, and counting only the returned page
        inflated the total."""
        from agno.agent import Agent

        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("shadowed"))
        for index in range(4):
            _create_agent(studio, _agent_request(f"other{index}"))

        runner = StudioRunnerTools(
            registry=registry,
            db=db,
            list_limit=2,
            agents_list=[Agent(id="shadowed", name="code-shadowed", model=OpenAIResponses(id="gpt-5.4"))],
        )
        listing = _loads(runner.list_agents())
        assert listing["total"] == 5

    def test_a_component_without_a_db_does_not_claim_to_declare_one(self, db, registry, caplog):
        model_config = {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"}
        db.upsert_component(component_id="plain", component_type="agent", name="plain")
        db.upsert_config(
            component_id="plain", config={"id": "plain", "name": "plain", "model": model_config}, stage="published"
        )

        with caplog.at_level("WARNING"):
            assert StudioRunnerTools(registry=registry, db=db)._agent_for_run("plain") is not None
        assert not any("declares a db" in record.message for record in caplog.records)

    def test_a_shadowed_id_is_one_component_not_two(self, db, registry):
        """A code component shadows the stored one it shares an id with at
        dispatch, so the pair is one component to run rather than two to
        count."""
        from agno.agent import Agent

        studio = _studio(registry, db)
        _create_agent(studio, _agent_request("dup"))

        runner = StudioRunnerTools(
            registry=registry,
            db=db,
            agents_list=[Agent(id="dup", name="dup-in-code", model=OpenAIResponses(id="gpt-5.4"))],
        )
        listing = _loads(runner.list_agents())
        assert [entry["id"] for entry in listing["agents"]] == ["dup"]
        assert listing["count"] == 1 and listing["total"] == 1
        # The code component is the one that runs, so it is the one listed.
        assert listing["agents"][0]["name"] == "dup-in-code"

    def test_a_nested_members_lost_model_is_refused_where_it_happened(self, db, registry):
        """A member declares its own models, so the loss belongs to the member
        rather than only to the component the caller named."""
        model_config = {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"}
        for component_id, component_type, extra in (
            ("member", "agent", {"reasoning_model": {"id": "o3-deep", "provider": "OpenAI"}}),
            ("crew", "team", {"members": [{"type": "agent", "agent_id": "member"}]}),
        ):
            config = {"id": component_id, "name": component_id, "model": model_config}
            config.update(extra)
            db.upsert_component(component_id=component_id, component_type=component_type, name=component_id)
            db.upsert_config(component_id=component_id, config=config, stage="published")

        error = _loads(StudioRunnerTools(registry=registry, db=db).run_team("crew", "hi"))["error"]
        assert "reasoning_model" in error and "member" in error

    def test_a_declared_model_that_cannot_be_rebuilt_is_refused(self, db, registry):
        """A reasoning, parser or output model is serialized and never read back
        -- from_dict's reconstruction for all three is still a TODO (#9452) --
        so a component declaring one always answers through a different
        pipeline than it was configured for. The run succeeds, which makes a
        log line invisible to whoever asked, so dispatch refuses instead. Until
        #9452 lands, not dispatchable is what the capability actually is."""
        from agno.agent import Agent

        Agent(
            id="rich",
            name="Rich",
            model=OpenAIResponses(id="gpt-5.4"),
            reasoning_model=OpenAIResponses(id="o3-deep"),
        ).save(db=db)

        runner = StudioRunnerTools(registry=registry, db=db)
        assert "reasoning_model" in _loads(runner.run_agent("rich", "hi"))["error"]

        # Reads and edits still load it, so the declaration stays repairable.
        assert runner._find_agent("rich") is not None

        # A component declaring none of them is untouched.
        Agent(id="plain", name="Plain", model=OpenAIResponses(id="gpt-5.4")).save(db=db)
        assert runner._agent_for_run("plain") is not None

    def test_an_anonymous_caller_is_not_written_into_the_targets_user(self, db):
        """The module promises per-user state lands on the human who asked and
        never on a service default. Passing None for a caller that HAS a context
        but no user is indistinguishable from passing no override, so the target
        fell back to its own configured user_id and the anonymous run was
        written into that user's memory."""
        from agno.agent import Agent
        from agno.registry import Registry

        owned = Agent(id="svc", name="Svc", model=OpenAIResponses(id="gpt-5.4"), user_id="service-default")
        unowned = Agent(id="plain", name="Plain", model=OpenAIResponses(id="gpt-5.4"))
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, agents_list=[owned, unowned])
        anonymous = RunContext(run_id="r1", session_id="s1", user_id=None)

        error = _loads(runner.run_agent("svc", "hi", _agno_run_context=anonymous)).get("error", "")
        assert "no user" in error and "service-default" in error

        # The three neighbouring cases must still run. A target with no user of
        # its own has nothing to capture the run; a caller with no context at
        # all is not claiming to be anyone, so the component's own
        # configuration is the only identity there is.
        assert runner._caller_user_id(anonymous, unowned) is None
        assert runner._caller_user_id(None, owned) is None
        assert runner._caller_user_id(RunContext(run_id="r", session_id="s", user_id="alice"), owned) == "alice"

    def test_a_copy_answering_from_another_provider_is_not_faithful(self):
        """Two providers share a model id readily, so comparing the id alone let
        a copy answer from a different pipeline under the right name."""
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat

        original = Agent(id="x", name="X", model=OpenAIResponses(id="gpt-5.4"))
        swapped = Agent(id="x", name="X", model=OpenAIChat(id="gpt-5.4"))
        assert StudioRunnerTools._copy_lost_identity(original, swapped)

        same = Agent(id="x", name="X", model=OpenAIResponses(id="gpt-5.4"))
        assert not StudioRunnerTools._copy_lost_identity(original, same)

        # Connection settings are deliberately not compared: they are never
        # serialized, so every DB-loaded component would be refused (#9420).
        without_endpoint = Agent(id="x", name="X", model=OpenAIResponses(id="gpt-5.4"))
        with_endpoint = Agent(
            id="x", name="X", model=OpenAIResponses(id="gpt-5.4", base_url="https://private.internal/v1")
        )
        assert not StudioRunnerTools._copy_lost_identity(with_endpoint, without_endpoint)

    def test_dispatch_refuses_a_db_it_would_redirect_but_not_one_that_matches(self, db):
        """A declared db that cannot be rebuilt falls back to the catalog db.
        When that is a different store the component's sessions and memory
        durably land somewhere other than configured, which the caller cannot
        see from the answer it gets. Refusing every fallback was tried and
        reverted -- it makes each adapter whose connection cannot serialize
        undispatchable -- so only a genuine mismatch is refused."""
        model_config = {"name": "OpenAIResponses", "id": "gpt-5.4", "provider": "OpenAI"}
        for component_id, db_config in (
            ("elsewhere", {"type": "redis", "id": "tenant-private"}),
            ("retabled", {"id": db.id, "session_table": "somewhere_else"}),
            ("matching", {"id": db.id}),
        ):
            db.upsert_component(component_id=component_id, component_type="agent", name=component_id)
            db.upsert_config(
                component_id=component_id,
                stage="published",
                config={"id": component_id, "model": model_config, "db": db_config},
            )

        runner = StudioRunnerTools(db=db)
        for component_id in ("elsewhere", "retabled"):
            error = _loads(runner.run_agent(component_id, "hi")).get("error", "")
            assert "somewhere other than configured" in error, component_id

        # The one that names the db it would actually get still dispatches --
        # that is what keeps the unserializable adapters working.
        assert runner._agent_for_run("matching") is not None

        # And a read still loads either way, so the reference stays repairable.
        assert runner._find_agent("elsewhere") is not None

    def test_a_tool_is_refused_for_what_it_lost_not_for_being_declared(self, db):
        # Not every serialized tool needs the registry: a provider-native tool
        # and an external_execution one carry themselves. Refusing because the
        # config declares tools at all would refuse those for what their
        # neighbours need, so the refusal has to come from comparing what came
        # back against what was declared -- and to name it.
        model_config = {"id": "gpt-5.4", "provider": "OpenAI"}
        db.upsert_component(component_id="armed", component_type="agent", name="armed")
        db.upsert_config(
            component_id="armed",
            stage="published",
            config={"id": "armed", "name": "armed", "model": model_config, "tools": [{"name": "calculator"}]},
        )

        error = _loads(StudioRunnerTools(db=db).run_agent("armed", "hi"))["error"]
        # The honest check names what was lost; the blanket pre-guard could only
        # say the config mentioned tools.
        assert "calculator" in error or "1 of 1" in error

    def test_no_reference_walk_reads_the_callers_own_data(self):
        # A step carries free-form user JSON beside its own fields. A walk over
        # every value reads a key named agent_id there as a graph reference.
        from agno.tools.studio_runner import (
            _component_references,
            _references_executors,
            _references_idless_components,
        )

        noisy = {
            "steps": [
                {
                    "name": "s",
                    "agent_id": "real",
                    "human_review": {
                        "user_input_schema": [{"agent_id": "NOISE", "team_id": None, "executor_ref": "NOISE"}]
                    },
                }
            ]
        }
        assert _component_references("workflow", noisy) == [("agent", "real")]
        assert not _references_executors("workflow", noisy)
        assert not _references_idless_components("workflow", noisy)

        # The same walks must still see what a step really declares.
        real = {"steps": [{"name": "s", "steps": [{"name": "n", "team_id": "crew", "executor_ref": "fn"}]}]}
        assert _component_references("workflow", real) == [("team", "crew")]
        assert _references_executors("workflow", real)


class TestSubSessionDerivation:
    """The derived id keys one session per component per calling conversation, so
    it has to be stable, injective and bounded."""

    def test_same_caller_and_component_reuse_one_session(self):
        assert _sub_session("agent", "a1") == _sub_session("agent", "a1")

    def test_caller_component_and_type_each_change_the_session(self):
        base = _sub_session("agent", "a1")
        assert base != _sub_session("agent", "a1", caller_session="other-sess")
        assert base != _sub_session("agent", "a2")
        # Ids are unique per type only, so an agent and a team sharing one id must
        # not share a session row.
        assert base != _sub_session("team", "a1")

    def test_delimiter_in_a_part_cannot_forge_another_pair(self):
        # Joining is not injective once a part can contain the delimiter, and a
        # runner dispatched by a runner produces exactly that. Joined, both of
        # these would read "a--agent--b--agent--c" and each component would load
        # the other's history.
        assert _sub_session("agent", "c", caller_session="a--agent--b") != _sub_session(
            "agent", "b--agent--c", caller_session="a"
        )

    def test_length_is_bounded_however_long_the_inputs(self):
        # MySQL and SingleStore cap session_id at 128 characters, and nested
        # dispatch grows a joined id without limit.
        derived = _sub_session("workflow", "w" * 4000, caller_session="s" * 4000)
        assert derived is not None and len(derived) <= 128

    def test_sessionless_caller_gets_no_session(self):
        assert StudioRunnerTools._sub_session_id(None, "agent", "a1") is None
        assert StudioRunnerTools._sub_session_id(_context(session_id=""), "agent", "a1") is None

    def test_two_users_on_one_caller_session_get_their_own(self):
        # Two people can share a caller session -- a team channel, a shared
        # assistant -- and the target must not hand them one conversation.
        alice = RunContext(run_id="r1", session_id="shared", user_id="alice")
        bob = RunContext(run_id="r2", session_id="shared", user_id="bob")
        assert StudioRunnerTools._sub_session_id(alice, "agent", "a1") != StudioRunnerTools._sub_session_id(
            bob, "agent", "a1"
        )

    def test_an_anonymous_caller_cannot_be_impersonated(self):
        # The sentinel standing in for "no user" has to be one no real user id
        # can spell, or naming yourself after it would take over that session.
        anonymous = RunContext(run_id="r1", session_id="shared", user_id=None)
        impostor = RunContext(run_id="r2", session_id="shared", user_id="anonymous")
        assert StudioRunnerTools._sub_session_id(anonymous, "agent", "a1") != StudioRunnerTools._sub_session_id(
            impostor, "agent", "a1"
        )

    def test_derivation_is_frozen(self):
        # The derived id is persisted in session rows, so a change to the
        # derivation orphans every existing sub-session. This literal is the
        # contract: sha256 of the length-prefixed parts (caller session, caller
        # user, component type, component id), first 32 hex chars, prefixed
        # with the component type.
        assert _sub_session("agent", "a1") == "agent-f6767baa5b7618d17f8691ef84c1b2fb"


class TestResultMedia:
    def test_response_audio_is_reported(self):
        """A voice run puts its whole answer in response_audio and leaves content
        empty. Without this the result reads as a successful run that said nothing."""

        class _VoiceRunOutput:
            run_id = "run-v"
            session_id = "sub-sess-v"
            status = RunStatus.completed
            content = None
            response_audio = object()

        payload = _loads(StudioRunnerTools._run_payload("agent_id", "voice", _VoiceRunOutput()))
        assert payload["status"] == "COMPLETED"
        assert payload["media"] == {"response_audio": 1}

    def test_no_media_key_when_the_run_produced_none(self):
        payload = _loads(StudioRunnerTools._run_payload("agent_id", "stub", _StubRunOutput()))
        assert "media" not in payload


class TestMemberIsolation:
    def test_member_without_deep_copy_is_shared_by_design(self, db):
        # A remote proxy holds no per-run state, so Team.deep_copy shares it.
        # The dispatch guard must not read that as a failed copy.
        from agno.agent.agent import Agent as AgentClass
        from agno.agent.remote import RemoteAgent
        from agno.team.team import Team as TeamClass

        remote = RemoteAgent(base_url="http://remote:7777", agent_id="explorer", timeout=60.0)
        local = AgentClass(id="summarizer", name="Summarizer", model=OpenAIResponses(id="gpt-5.4"))
        team = TeamClass(
            id="distributed-crew", name="Distributed Crew", model=OpenAIResponses(id="gpt-5.4"), members=[local, remote]
        )

        fresh = StudioRunnerTools._fresh_copy(team)
        assert fresh is not team
        assert fresh.members[1] is remote

    def test_shared_member_nested_in_a_team_of_teams_refuses_dispatch(self, db):
        # An inner team whose own member copy failed comes back as a new object
        # holding the shared grandchild, so the check has to descend.
        from agno.agent.agent import Agent as AgentClass
        from agno.team.team import Team as TeamClass

        class _UncopyableAgent(AgentClass):
            def __init__(self, topic, **kwargs):
                self.topic = topic
                super().__init__(**kwargs)

        grandchild = _UncopyableAgent("ai", id="grandchild", name="Grandchild", model=OpenAIResponses(id="gpt-5.4"))
        inner = TeamClass(id="inner", name="Inner", model=OpenAIResponses(id="gpt-5.4"), members=[grandchild])
        outer = TeamClass(id="outer", name="Outer", model=OpenAIResponses(id="gpt-5.4"), members=[inner])

        out = _loads(StudioRunnerTools(db=db, teams_list=[outer]).run_team("outer", "hi"))
        assert "still shares member 'grandchild'" in out["error"]

    def test_healthy_nested_team_dispatches(self, db):
        from agno.agent.agent import Agent as AgentClass
        from agno.team.team import Team as TeamClass

        grandchild = AgentClass(id="gc", name="GC", model=OpenAIResponses(id="gpt-5.4"))
        inner = TeamClass(id="inner-ok", name="Inner Ok", model=OpenAIResponses(id="gpt-5.4"), members=[grandchild])
        outer = TeamClass(id="outer-ok", name="Outer Ok", model=OpenAIResponses(id="gpt-5.4"), members=[inner])

        fresh = StudioRunnerTools._fresh_copy(outer)
        assert fresh.members[0].members[0] is not grandchild


class TestIncludeAllComponents:
    """run_* dispatch what list_* report. Code-defined components arrive through
    the registry, which is passed so persisted components can rehydrate, so
    running them is opt-in."""

    @pytest.fixture
    def registry_with_agent(self, db):
        from agno.registry import Registry

        return Registry(name="R", dbs=[db], agents=[_StubAgent()])

    def test_registry_component_is_not_listed(self, registry_with_agent, db):
        runner = StudioRunnerTools(registry=registry_with_agent, db=db)
        assert _loads(runner.list_agents())["agents"] == []

    def test_registry_component_is_refused_by_default(self, registry_with_agent, db):
        runner = StudioRunnerTools(registry=registry_with_agent, db=db)
        error = _loads(runner.run_agent("stub", "hi", _agno_run_context=_context()))["error"]
        assert "include_all_components" in error
        assert registry_with_agent.agents[0].seen is None  # never dispatched

    def test_flag_admits_the_registry_component(self, registry_with_agent, db):
        runner = StudioRunnerTools(registry=registry_with_agent, db=db, include_all_components=True)
        assert _loads(runner.run_agent("stub", "hi", _agno_run_context=_context()))["agent_id"] == "stub"
        assert registry_with_agent.agents[0].seen is not None

    def test_explicit_list_needs_no_flag(self, db):
        # Passing the component IS the allowlist.
        runner = StudioRunnerTools(db=db, agents_list=[_StubAgent()])
        assert _loads(runner.run_agent("stub", "hi", _agno_run_context=_context()))["agent_id"] == "stub"

    def test_reads_still_see_the_registry_component(self, registry_with_agent, db):
        # Only dispatch is gated; get/edit/member resolution keep the full set.
        runner = StudioRunnerTools(registry=registry_with_agent, db=db)
        assert runner._find_agent("stub") is registry_with_agent.agents[0]
        assert runner._find_agent("stub", for_dispatch=True) is None

    def test_studio_tools_keeps_its_reach(self, registry_with_agent, db):
        # StudioTools holds the registry as its build palette, so its run_* are unchanged.
        assert _studio(registry_with_agent, db)._runner_tools.include_all_components is True


class TestPartialRegistryFailsClosed:
    """A registry that is present but incomplete degrades silently in from_dict:
    an unresolved tool binds to entrypoint=None, a missing schema is deleted."""

    def _config(self, **overrides):
        config = {"id": "rep", "name": "Rep", "instructions": "help"}
        config.update(overrides)
        return config

    def test_unresolved_tool_refuses_dispatch(self, db):
        from agno.tools.function import Function

        component = type("C", (), {"tools": [Function(name="secret_tool", entrypoint=None)]})()
        with pytest.raises(Exception) as excinfo:
            StudioRunnerTools(db=db)._require_faithful_rebuild(
                component, self._config(tools=[{"name": "secret_tool"}]), "agent", "rep"
            )
        assert "secret_tool" in str(excinfo.value)

    def test_dropped_knowledge_refuses_dispatch(self, db):
        component = type("C", (), {"knowledge": None})()
        with pytest.raises(Exception) as excinfo:
            StudioRunnerTools(db=db)._require_faithful_rebuild(
                component, self._config(knowledge={"name": "handbook"}), "agent", "rep"
            )
        assert "handbook" in str(excinfo.value)

    def test_dropped_output_schema_refuses_dispatch(self, db):
        component = type("C", (), {"output_schema": None})()
        with pytest.raises(Exception) as excinfo:
            StudioRunnerTools(db=db)._require_faithful_rebuild(
                component, self._config(output_schema="Report"), "agent", "rep"
            )
        assert "Report" in str(excinfo.value)

    def test_inline_dict_schema_is_not_a_registry_reference(self, db):
        # Only the string form is a reference; an inline schema carries itself.
        component = type("C", (), {"output_schema": None})()
        StudioRunnerTools(db=db)._require_faithful_rebuild(
            component, self._config(output_schema={"type": "object"}), "agent", "rep"
        )

    def test_faithful_rebuild_passes(self, db):
        from agno.tools.function import Function

        component = type(
            "C",
            (),
            {"tools": [Function(name="ok", entrypoint=lambda: None)], "knowledge": object(), "output_schema": dict},
        )()
        StudioRunnerTools(db=db)._require_faithful_rebuild(
            component,
            self._config(tools=[{"name": "ok"}], knowledge={"name": "kb"}, output_schema="Report"),
            "agent",
            "rep",
        )

    def test_dispatch_of_a_stored_component_refuses_on_a_partial_registry(self, db):
        """End to end through run_agent, so the check is wired into the load path and
        not merely available: a tool-bearing component built against a full registry
        must refuse to run against one that lost the tool, while reads keep working."""
        from agno.registry import Registry
        from agno.tools.calculator import CalculatorTools

        full = Registry(name="full", dbs=[db], models=[OpenAIResponses(id="gpt-5.4")], tools=[CalculatorTools()])
        studio = _studio(full, db, default_model=ModelRef(id="gpt-5.4"))
        _create_agent(
            studio,
            AgentCreate(
                name="Calc Agent",
                instructions="math",
                tools=[ToolRef(kind="toolkit", name="calculator")],
            ),
        )

        partial = Registry(name="partial", dbs=[db], models=[OpenAIResponses(id="gpt-5.4")])
        error = _loads(
            StudioRunnerTools(registry=partial, db=db).run_agent("calc-agent", "2+2", _agno_run_context=_context())
        )["error"]
        assert "calc-agent" in error and "registry" in error

        # The component stays loadable and repairable on the same partial registry.
        partial_studio = _studio(partial, db)
        assert _data(partial_studio.get_agent("calc-agent", _agno_run_context=_context())).component_id == "calc-agent"

    def test_a_component_without_registry_references_is_unaffected(self, db):
        from agno.registry import Registry

        registry = Registry(name="r", dbs=[db], models=[OpenAIResponses(id="gpt-5.4")])
        studio = _studio(registry, db, default_model=ModelRef(id="gpt-5.4"))
        _create_agent(
            studio,
            AgentCreate(name="Plain", instructions="hi"),
        )
        assert StudioRunnerTools(registry=registry, db=db)._find_agent("plain", for_dispatch=True) is not None


class TestMemberStructureFidelity:
    """Whether a member is aliased is _shared_member's question (TestMemberIsolation).
    This is the other half: whether the copy holds the same members at all."""

    def test_swapped_member_is_refused(self):
        from agno.agent import Agent
        from agno.team import Team

        class SwapsMember(Team):
            def deep_copy(self, **kwargs):
                return SwapsMember(id=self.id, name=self.name, members=[Agent(id="impostor", name="Impostor")])

        with pytest.raises(Exception) as excinfo:
            StudioRunnerTools._fresh_copy(SwapsMember(id="t", name="T", members=[Agent(id="real", name="Real")]))
        assert "real" in str(excinfo.value)

    def test_dropped_member_is_refused(self):
        from agno.agent import Agent
        from agno.team import Team

        class DropsMember(Team):
            def deep_copy(self, **kwargs):
                return DropsMember(id=self.id, name=self.name, members=[Agent(id="a", name="A")])

        original = DropsMember(id="t", name="T", members=[Agent(id="a", name="A"), Agent(id="b", name="B")])
        with pytest.raises(Exception) as excinfo:
            StudioRunnerTools._fresh_copy(original)
        assert "member count changed" in str(excinfo.value)

    def test_swap_nested_below_the_first_level_is_refused(self):
        from agno.agent import Agent
        from agno.team import Team

        class SwapsGrandchild(Team):
            def deep_copy(self, **kwargs):
                inner = Team(id="inner", name="Inner", members=[Agent(id="impostor", name="Impostor")])
                return SwapsGrandchild(id=self.id, name=self.name, members=[inner])

        original = SwapsGrandchild(
            id="outer", name="Outer", members=[Team(id="inner", name="Inner", members=[Agent(id="real", name="Real")])]
        )
        with pytest.raises(Exception) as excinfo:
            StudioRunnerTools._fresh_copy(original)
        assert "real" in str(excinfo.value)

    def test_workflow_step_whose_executor_holds_a_shared_member_is_refused(self, db):
        """A step whose team is a fresh copy still leaks if one of that team's own
        members is the registry singleton, so the check descends into the executor."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.team import Team

        shared_member = Agent(id="shared", name="Shared")
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db], agents=[shared_member]), db=db)

        step = type("S", (), {"name": "s", "agent": None, "team": Team(id="t", name="T", members=[shared_member])})()
        with pytest.raises(Exception) as excinfo:
            runner._require_isolated_steps(type("W", (), {"steps": [step]})(), "wf")
        assert "shared" in str(excinfo.value)

    def test_step_member_without_deep_copy_is_shared_by_design(self, db):
        """The step check descends into an executor's members, so it has to honour the
        same rule _shared_member does: a member with no deep_copy holds no per-run
        state to isolate, and refusing it would make a remote member undispatchable."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.team import Team

        class _RemoteLike(Agent):
            deep_copy = None  # a remote proxy: nothing to isolate

        remote = _RemoteLike(id="remote", name="Remote")
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db], agents=[remote]), db=db)
        step = type("S", (), {"name": "s", "agent": None, "team": Team(id="t", name="T", members=[remote])})()
        runner._require_isolated_steps(type("W", (), {"steps": [step]})(), "wf")

    def test_step_executor_itself_is_refused_without_that_exemption(self, db):
        from agno.agent import Agent
        from agno.registry import Registry

        class _RemoteLike(Agent):
            deep_copy = None

        remote = _RemoteLike(id="remote", name="Remote")
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db], agents=[remote]), db=db)
        step = type("S", (), {"name": "s", "agent": remote, "team": None})()
        with pytest.raises(Exception):
            runner._require_isolated_steps(type("W", (), {"steps": [step]})(), "wf")

    def test_code_defined_workflow_step_executor_that_copies_to_itself_is_refused(self, db):
        """A workflow holds steps, not members, so the member checks say nothing
        about a step executor. An executor whose deep_copy returns the original
        dispatches the shared instance, and per-run mutation of it crosses
        callers."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        class _SelfCopy(Agent):
            def deep_copy(self, *, update=None):
                return self

        shared = _SelfCopy(id="leaky", name="Leaky", model=OpenAIResponses(id="gpt-5.4"))
        wf = Workflow(id="flow", name="Flow", db=db, steps=[Step(name="s", agent=shared)])
        # Not in the registry: the copy is judged against the original, so the
        # refusal does not depend on knowing the registry's instances.
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, workflows_list=[wf])

        result = _loads(runner.run_workflow("flow", "hello"))
        assert "agent is still shared" in result["error"]

    def test_step_executor_whose_member_survives_the_copy_is_refused(self, db):
        """A step executor that copies cleanly still leaks when one of its own
        members did not, so the check descends into the copied executor."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.team import Team
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        class _SelfCopy(Agent):
            def deep_copy(self, *, update=None):
                return self

        member = _SelfCopy(id="nested-leaky", name="Nested", model=OpenAIResponses(id="gpt-5.4"))
        crew = Team(id="crew", name="Crew", model=OpenAIResponses(id="gpt-5.4"), members=[member])
        wf = Workflow(id="flow", name="Flow", db=db, steps=[Step(name="s", team=crew)])
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db]), db=db, workflows_list=[wf])

        result = _loads(runner.run_workflow("flow", "hello"))
        assert "still shares member 'nested-leaky'" in result["error"]

    def test_db_team_holding_a_registry_singleton_member_is_refused(self, db, registry):
        """Team.from_dict resolves a member the database does not hold through
        the registry and keeps whatever deep_copy returned, so a class that
        returns itself puts the singleton into the rebuilt team. The workflow
        path already refuses this graph; the team path has to agree."""
        from agno.agent import Agent

        class _SelfCopy(Agent):
            def deep_copy(self, *, update=None):
                return self

        worker = _SelfCopy(id="worker", name="Worker", model=OpenAIResponses(id="gpt-5.4"))
        registry.agents = [worker]
        db.upsert_component(component_id="crew", component_type="team", name="Crew")
        db.upsert_config(
            component_id="crew",
            stage="published",
            config={
                "id": "crew",
                "name": "Crew",
                "model": {"id": "gpt-5.4", "provider": "OpenAI"},
                "members": [{"type": "agent", "agent_id": "worker"}],
            },
        )
        runner = StudioRunnerTools(registry=registry, db=db)

        result = _loads(runner.run_team("crew", "hello"))
        assert "deep_copy returned the shared registry instance" in result["error"]

    def test_callable_factory_members_and_tools_do_not_crash_the_graph_walk(self):
        """members= and tools= accept callable factories, so the nested-tools walk
        must skip what it cannot iterate instead of crashing dispatch."""
        from agno.agent import Agent
        from agno.team import Team

        with_tool_factory = Team(id="t", name="T", members=[Agent(id="m", name="M", tools=lambda: [])])
        assert StudioRunnerTools._unresolved_below(with_tool_factory) is None

        lazy_members = Team(id="t2", name="T2", members=lambda: [Agent(id="m2", name="M2")])
        with_member_factory = Team(id="outer", name="Outer", members=[lazy_members])
        assert StudioRunnerTools._unresolved_below(with_member_factory) is None

    def test_step_executor_with_callable_factory_members_passes_the_isolation_check(self, db):
        """The isolation walk descends through member lists; a member team whose
        members= is a callable factory must be skipped, not iterated."""
        from agno.agent import Agent
        from agno.registry import Registry
        from agno.team import Team

        registered = Agent(id="registered", name="Registered")
        runner = StudioRunnerTools(registry=Registry(name="R", dbs=[db], agents=[registered]), db=db)
        lazy = Team(id="lazy", name="Lazy", members=lambda: [Agent(id="m", name="M")])
        step = type("S", (), {"name": "s", "agent": None, "team": Team(id="t", name="T", members=[lazy])})()
        runner._require_isolated_steps(type("W", (), {"steps": [step]})(), "wf")

    def test_copy_refusal_reaches_the_caller_as_its_own_message(self, db):
        """DispatchCopyError is a deliberate refusal with an actionable message, so it
        must not be wrapped as a resolve failure and logged with a traceback."""
        from agno.agent import Agent

        class _Broken(Agent):
            def deep_copy(self, **kwargs):
                return self

        runner = StudioRunnerTools(db=db, agents_list=[_Broken(id="b", name="B")])
        error = _loads(runner.run_agent("b", "x", _agno_run_context=_context()))["error"]
        assert error.startswith("deep_copy of 'b'")

    def test_an_ambiguous_registry_name_stays_ambiguous(self, db):
        """The undispatchable re-lookup must not swallow ambiguity into "not found"."""
        from agno.agent import Agent
        from agno.registry import Registry

        registry = Registry(name="R", dbs=[db], agents=[Agent(id="a1", name="Dup"), Agent(id="a2", name="Dup")])
        runner = StudioRunnerTools(registry=registry, db=db)
        error = _loads(runner.run_agent("Dup", "x", _agno_run_context=_context()))["error"]
        assert "Ambiguous" in error and "a1" in error and "a2" in error

    def test_a_null_member_id_still_loads_for_reads_and_edits(self, db):
        """The refusal is what stops the run; it must not also stop the component
        loading, or the bad reference can never be seen and repaired. Same split
        _require_faithful_rebuild uses."""
        config = {"id": "squad", "name": "Squad", "members": [{"agent_id": None, "name": "Ghost"}]}
        runner = StudioRunnerTools(db=db)

        # Dispatch refuses.
        with pytest.raises(Exception) as excinfo:
            runner._require_resolvable_member_ids("team", "squad", config)
        assert "no id" in str(excinfo.value)

        # The read path does not call it at all.
        import inspect

        source = inspect.getsource(StudioRunnerTools._load_team_from_db)
        before_call = source.split("_require_resolvable_member_ids")[0]
        assert "if for_dispatch:" in before_call


def test_dispatch_resolves_members_at_pinned_versions(tmp_path):
    """A dispatched team must execute the member versions pinned at team-save
    time, matching what get_team_by_id and Team.load resolve."""
    from agno.agent.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.registry import Registry
    from agno.team.team import Team
    from agno.tools.studio_runner import StudioRunnerTools

    db = SqliteDb(db_file=str(tmp_path / "runner_pin.db"))
    member = Agent(id="rp-member", name="Member", description="v1 desc")
    Team(id="rp-team", name="Team", members=[member]).save(db=db)
    member.description = "v3 desc"
    member.save(db=db)

    runner = StudioRunnerTools(registry=Registry(), db=db)
    team = runner._load_team_from_db("rp-team", for_dispatch=True)

    assert team is not None
    assert team.members[0].description == "v1 desc"


def test_dispatch_judges_pinned_members_against_their_pinned_config(tmp_path):
    """A republish of a pinned member must not make the pinned parent
    undispatchable: fidelity guards compare the rebuilt member against the
    config version it was built from, not the member's current version."""
    from agno.agent.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.models.openai import OpenAIChat
    from agno.registry import Registry
    from agno.team.team import Team
    from agno.tools.studio_runner import StudioRunnerTools

    def weather(city: str) -> str:
        """Weather."""
        return city

    db = SqliteDb(db_file=str(tmp_path / "pin_fidelity.db"))
    member = Agent(id="fm", name="Member")
    Team(id="ft", name="Team", members=[member]).save(db=db)
    member.model = OpenAIChat(id="gpt-4o-mini")
    member.tools = [weather]
    member.save(db=db)

    runner = StudioRunnerTools(registry=Registry(), db=db)
    team = runner._load_team_from_db("ft", for_dispatch=True)

    assert team is not None
    assert team.members[0].id == "fm"


def test_dispatch_never_mixes_config_and_links_from_different_versions(tmp_path):
    """A publish between the config read and any later read must not produce a
    hybrid artifact: links and guards use the version the config row resolved."""
    from agno.agent.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.registry import Registry
    from agno.team.team import Team
    from agno.tools.studio_runner import StudioRunnerTools

    db = SqliteDb(db_file=str(tmp_path / "race.db"))
    member = Agent(id="rv-m", name="M", description="v1")
    Team(id="rv-t", name="T", members=[member]).save(db=db)

    runner = StudioRunnerTools(registry=Registry(), db=db)
    real_get_config = db.get_config
    state = {"raced": False}

    def racy_get_config(component_id=None, version=None, **kwargs):
        row = real_get_config(component_id=component_id, version=version, **kwargs)
        if not state["raced"] and component_id == "rv-t":
            state["raced"] = True
            member.description = "v2"
            member.save(db=db)
            Team(id="rv-t", name="T", members=[member]).save(db=db)
        return row

    db.get_config = racy_get_config
    try:
        team_obj = runner._load_team_from_db("rv-t", for_dispatch=True)
    finally:
        del db.get_config

    assert team_obj is not None
    assert team_obj.members[0].description == "v1"
