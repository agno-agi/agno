from typing import Any, Optional

import pytest

from agno.run import RunContext
from agno.run.cancel import cleanup_run
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team import _run
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
    monkeypatch.setattr(team, "_has_async_db", lambda: False)
    monkeypatch.setattr(team, "initialize_team", lambda debug_mode=None: None)
    monkeypatch.setattr(team, "_initialize_session", lambda session_id=None, user_id=None: (session_id, user_id))
    monkeypatch.setattr(
        team,
        "_read_or_create_session",
        lambda session_id, user_id: TeamSession(session_id=session_id, user_id=user_id),
    )
    monkeypatch.setattr(team, "_update_metadata", lambda session: None)
    monkeypatch.setattr(team, "_initialize_session_state", lambda session_state, **kwargs: session_state)
    monkeypatch.setattr(team, "_load_session_state", lambda session, session_state: session_state)
    monkeypatch.setattr(team, "_resolve_run_dependencies", lambda run_context: None)
    monkeypatch.setattr(team, "_get_response_format", lambda run_context=None: None)
    monkeypatch.setattr(
        team,
        "_get_effective_filters",
        lambda knowledge_filters=None: {"team_filter": "default", **(knowledge_filters or {})},
    )


def test_run_respects_run_context_precedence(monkeypatch: pytest.MonkeyPatch):
    team = _make_precedence_test_team()
    _patch_team_dispatch_dependencies(team, monkeypatch)

    def fake_run(
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

    monkeypatch.setattr(team, "_run", fake_run)

    preserved_context = RunContext(
        run_id="team-preserve",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    _run.run(
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
    assert preserved_context.output_schema == {"ctx_schema": "keep"}

    override_context = RunContext(
        run_id="team-override",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    _run.run(
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
    _run.run(
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

    monkeypatch.setattr(team, "_arun", fake_arun)

    preserved_context = RunContext(
        run_id="ateam-preserve",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    await _run.arun(
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
    assert preserved_context.output_schema == {"ctx_schema": "keep"}

    override_context = RunContext(
        run_id="ateam-override",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    await _run.arun(
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
    await _run.arun(
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
