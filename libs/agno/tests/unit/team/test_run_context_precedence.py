from typing import Any, Optional

import pytest

from agno.run import RunContext
from agno.run.cancel import cleanup_run
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team import _init, _response, _run, _run_options, _storage, _utils
from agno.team.team import Team


def _make_precedence_test_team() -> Team:
    return Team(
        name="precedence-team",
        members=[],
        dependencies={"team_dep": "default"},
        knowledge_filters={"team_filter": "default"},
        metadata={"team_meta": "default"},
        output_schema={"type": "object", "properties": {"team": {"type": "string"}}},
    )


def _patch_team_dispatch_dependencies(team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_init, "_has_async_db", lambda team: False)
    monkeypatch.setattr(team, "initialize_team", lambda debug_mode=None: None)
    monkeypatch.setattr(_init, "_initialize_session", lambda team, session_id=None, user_id=None: (session_id, user_id))
    monkeypatch.setattr(
        _storage,
        "_read_or_create_session",
        lambda team, session_id=None, user_id=None: TeamSession(session_id=session_id, user_id=user_id),
    )
    monkeypatch.setattr(_storage, "_update_metadata", lambda team, session=None: None)
    monkeypatch.setattr(_init, "_initialize_session_state", lambda team, session_state=None, **kwargs: session_state)
    monkeypatch.setattr(_storage, "_load_session_state", lambda team, session=None, session_state=None: session_state)
    monkeypatch.setattr(_run, "_resolve_run_dependencies", lambda team, run_context: None)
    monkeypatch.setattr(_response, "get_response_format", lambda team, run_context=None: None)
    monkeypatch.setattr(
        _utils,
        "_get_effective_filters",
        lambda team, knowledge_filters=None: {"team_filter": "default", **(knowledge_filters or {})},
    )
    # Also patch in _run_options since resolve_run_options imports from _utils at call time
    monkeypatch.setattr(
        _run_options,
        "resolve_run_options",
        lambda team, **kwargs: _run_options.ResolvedRunOptions(
            stream=kwargs.get("stream") if kwargs.get("stream") is not None else (team.stream or False),
            stream_events=kwargs.get("stream_events")
            if kwargs.get("stream_events") is not None
            else (team.stream_events or False),
            yield_run_output=kwargs.get("yield_run_output") or False,
            add_history_to_context=kwargs.get("add_history_to_context")
            if kwargs.get("add_history_to_context") is not None
            else team.add_history_to_context,
            add_dependencies_to_context=kwargs.get("add_dependencies_to_context")
            if kwargs.get("add_dependencies_to_context") is not None
            else team.add_dependencies_to_context,
            add_session_state_to_context=kwargs.get("add_session_state_to_context")
            if kwargs.get("add_session_state_to_context") is not None
            else team.add_session_state_to_context,
            dependencies=kwargs.get("dependencies") if kwargs.get("dependencies") is not None else team.dependencies,
            knowledge_filters=({"team_filter": "default", **(kwargs.get("knowledge_filters") or {})})
            if (team.knowledge_filters or kwargs.get("knowledge_filters"))
            else None,
            metadata=({**(kwargs.get("metadata") or {}), **(team.metadata or {})})
            if (kwargs.get("metadata") is not None or team.metadata is not None)
            else None,
            output_schema=kwargs.get("output_schema")
            if kwargs.get("output_schema") is not None
            else team.output_schema,
        ),
    )


def test_run_respects_run_context_precedence(monkeypatch: pytest.MonkeyPatch):
    team = _make_precedence_test_team()
    _patch_team_dispatch_dependencies(team, monkeypatch)

    def fake_run(
        team,
        run_response: TeamRunOutput,
        run_context: RunContext,
        session: TeamSession,
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Any] = None,
        stream_events: bool = False,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> TeamRunOutput:
        cleanup_run(run_response.run_id)  # type: ignore[arg-type]
        return run_response

    monkeypatch.setattr(_run, "_run", fake_run)

    preserved_context = RunContext(
        run_id="team-preserve",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    _run.run_dispatch(
        team=team,
        input="hello",
        run_id="run-preserve",
        session_id="session-1",
        stream=False,
        run_context=preserved_context,
    )
    assert preserved_context.dependencies == {"ctx_dep": "keep"}
    assert preserved_context.knowledge_filters == {"ctx_filter": "keep"}
    assert preserved_context.metadata == {"ctx_meta": "keep"}
    # Team always sets output_schema from resolved options (for workflow reuse)
    assert preserved_context.output_schema == {"type": "object", "properties": {"team": {"type": "string"}}}

    override_context = RunContext(
        run_id="team-override",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    _run.run_dispatch(
        team=team,
        input="hello",
        run_id="run-override",
        session_id="session-1",
        stream=False,
        run_context=override_context,
        dependencies={"call_dep": "override"},
        knowledge_filters={"call_filter": "override"},
        metadata={"call_meta": "override"},
        output_schema={"call_schema": "override"},
    )
    assert override_context.dependencies == {"call_dep": "override"}
    assert override_context.knowledge_filters == {"team_filter": "default", "call_filter": "override"}
    assert override_context.metadata == {"call_meta": "override", "team_meta": "default"}
    assert override_context.output_schema == {"call_schema": "override"}

    empty_context = RunContext(
        run_id="team-empty",
        session_id="session-1",
        session_state={},
        dependencies=None,
        knowledge_filters=None,
        metadata=None,
        output_schema=None,
    )
    _run.run_dispatch(
        team=team,
        input="hello",
        run_id="run-empty",
        session_id="session-1",
        stream=False,
        run_context=empty_context,
    )
    assert empty_context.dependencies == {"team_dep": "default"}
    assert empty_context.knowledge_filters == {"team_filter": "default"}
    assert empty_context.metadata == {"team_meta": "default"}
    assert empty_context.output_schema == {"type": "object", "properties": {"team": {"type": "string"}}}


@pytest.mark.asyncio
async def test_arun_respects_run_context_precedence(monkeypatch: pytest.MonkeyPatch):
    team = _make_precedence_test_team()
    _patch_team_dispatch_dependencies(team, monkeypatch)

    async def fake_arun(
        team,
        run_response: TeamRunOutput,
        run_context: RunContext,
        session_id: str,
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Any] = None,
        stream_events: bool = False,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> TeamRunOutput:
        return run_response

    monkeypatch.setattr(_run, "_arun", fake_arun)

    preserved_context = RunContext(
        run_id="ateam-preserve",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    await _run.arun_dispatch(
        team=team,
        input="hello",
        run_id="arun-preserve",
        session_id="session-1",
        stream=False,
        run_context=preserved_context,
    )
    assert preserved_context.dependencies == {"ctx_dep": "keep"}
    assert preserved_context.knowledge_filters == {"ctx_filter": "keep"}
    assert preserved_context.metadata == {"ctx_meta": "keep"}
    # Team always sets output_schema from resolved options (for workflow reuse)
    assert preserved_context.output_schema == {"type": "object", "properties": {"team": {"type": "string"}}}

    override_context = RunContext(
        run_id="ateam-override",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    await _run.arun_dispatch(
        team=team,
        input="hello",
        run_id="arun-override",
        session_id="session-1",
        stream=False,
        run_context=override_context,
        dependencies={"call_dep": "override"},
        knowledge_filters={"call_filter": "override"},
        metadata={"call_meta": "override"},
        output_schema={"call_schema": "override"},
    )
    assert override_context.dependencies == {"call_dep": "override"}
    assert override_context.knowledge_filters == {"team_filter": "default", "call_filter": "override"}
    assert override_context.metadata == {"call_meta": "override", "team_meta": "default"}
    assert override_context.output_schema == {"call_schema": "override"}

    empty_context = RunContext(
        run_id="ateam-empty",
        session_id="session-1",
        session_state={},
        dependencies=None,
        knowledge_filters=None,
        metadata=None,
        output_schema=None,
    )
    await _run.arun_dispatch(
        team=team,
        input="hello",
        run_id="arun-empty",
        session_id="session-1",
        stream=False,
        run_context=empty_context,
    )
    assert empty_context.dependencies == {"team_dep": "default"}
    assert empty_context.knowledge_filters == {"team_filter": "default"}
    assert empty_context.metadata == {"team_meta": "default"}
    assert empty_context.output_schema == {"type": "object", "properties": {"team": {"type": "string"}}}
