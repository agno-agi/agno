"""Recall tools search by topic and time, stay inside their component, and read partial sessions."""

import inspect
import json

import pytest

from agno.agent import _default_tools
from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.session_filters import matches_session_filter, normalize_session_filter
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.run.agent import RunInput, RunOutput
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.session.summary import SessionSummary
from agno.team import _default_tools as _team_default_tools
from agno.team.team import Team


def _runs(session_id, inputs, run_class=RunOutput, **owner):
    return [
        run_class(
            run_id=f"{session_id}-{i}",
            session_id=session_id,
            input=RunInput(input_content=text),
            content=f"Answer {i}",
            messages=[Message(role="user", content=text), Message(role="assistant", content=f"Answer {i}")],
            **owner,
        )
        for i, text in enumerate(inputs, start=1)
    ]


def _seed(db, session_class=AgentSession, run_class=RunOutput, key="agent_id"):
    sessions = [
        session_class(
            session_id="billing-session",
            user_id="alice",
            created_at=100,
            summary=SessionSummary(summary="Fixed the billing export bug"),
            runs=_runs(
                "billing-session",
                ["Q1", "The S3 export failed with AccessDenied", "Q3", "Q4"],
                run_class,
                **{key: "support"},
            ),
            **{key: "support"},
        ),
        session_class(
            session_id="named-session",
            user_id="alice",
            created_at=200,
            session_data={"session_name": "Onboarding plan"},
            runs=_runs("named-session", ["Draft a checklist"], run_class, **{key: "support"}),
            **{key: "support"},
        ),
        session_class(
            session_id="foreign-session",
            user_id="alice",
            created_at=300,
            summary=SessionSummary(summary="billing too"),
            runs=_runs("foreign-session", ["AccessDenied again"], run_class, **{key: "someone-else"}),
            **{key: "someone-else"},
        ),
    ]
    for session in sessions:
        db.upsert_session(session)
        # SQL adapters keep runs in their own table, written run by run.
        for index, run in enumerate(session.runs):
            db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=index)


@pytest.fixture(params=["sqlite", "memory"])
def db(request, tmp_path):
    # SQLite searches natively; the in-memory store takes the portable fallback.
    if request.param == "sqlite":
        return SqliteDb(db_file=str(tmp_path / "recall.db"))
    return InMemoryDb()


def _ids(result):
    return [row["session_id"] for row in json.loads(result)]


def test_agent_search_by_name_summary_and_run_content(db):
    _seed(db)
    search = _default_tools.get_search_past_sessions_function(Agent(id="support", db=db))

    assert _ids(search(query="BILLING")) == ["billing-session"]
    assert _ids(search(query="onboarding")) == ["named-session"]
    # Only the conversation mentions it, and the other agent's matching session stays hidden.
    assert _ids(search(query="accessdenied")) == ["billing-session"]
    assert _ids(search(query="answer 1")) == ["named-session", "billing-session"]
    assert _ids(search(query="%")) == []

    preview = json.loads(search(query="billing"))[0]
    assert preview["summary"] == "Fixed the billing export bug"


def test_agent_search_by_time(db):
    _seed(db)
    search = _default_tools.get_search_past_sessions_function(Agent(id="support", db=db))

    assert _ids(search(until="1970-01-01T00:02:30Z")) == ["billing-session"]
    assert set(_ids(search(since="1970-01-01"))) == {"billing-session", "named-session"}
    assert _ids(search(since="2999-01-01")) == []
    assert "error" in json.loads(search(since="last tuesday"))


def test_agent_listing_stays_inside_component(db):
    _seed(db)
    search = _default_tools.get_search_past_sessions_function(Agent(id="support", db=db))
    assert set(_ids(search())) == {"billing-session", "named-session"}


def test_agent_read_partial_and_refuses_foreign_session(db):
    _seed(db)
    read = _default_tools.get_read_past_session_function(Agent(id="support", db=db))

    tail = read(session_id="billing-session", start=-2)
    assert "Runs 3-4 of 4" in tail
    assert "Q3" in tail and "Answer 4" in tail and "Q1" not in tail

    assert "Runs 3-4 of 4" in read(session_id="billing-session", num_runs=-2)

    first = read(session_id="billing-session", num_runs=1)
    assert "Runs 1-1 of 4" in first and "AccessDenied" not in first

    truncated = read(session_id="billing-session", max_chars=20)
    assert truncated.endswith("pass a later start)")

    assert read(session_id="foreign-session") == "Session not found."


@pytest.mark.asyncio
async def test_agent_async_tools_match_sync(db):
    _seed(db)
    agent = Agent(id="support", db=db)
    search = await _default_tools.aget_search_past_sessions_function(agent)
    read = await _default_tools.aget_read_past_session_function(agent)

    assert _ids(await search.entrypoint(query="accessdenied")) == ["billing-session"]
    assert set(_ids(await search.entrypoint())) == {"billing-session", "named-session"}
    assert "error" in json.loads(await search.entrypoint(until="not a date"))
    assert "Runs 4-4 of 4" in await read.entrypoint(session_id="billing-session", start=-1)
    assert await read.entrypoint(session_id="foreign-session") == "Session not found."


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_team_tools_search_and_read(db, async_mode):
    _seed(db, TeamSession, TeamRunOutput, key="team_id")
    team = Team(id="support", members=[], db=db)
    search = _team_default_tools._search_past_sessions_function(team, async_mode=async_mode)
    read = _team_default_tools._read_past_session_function(team, async_mode=async_mode)

    async def call(function, **kwargs):
        result = function.entrypoint(**kwargs)
        return await result if inspect.isawaitable(result) else result

    assert _ids(await call(search, query="accessdenied")) == ["billing-session"]
    assert _ids(await call(search, until="1970-01-01T00:02:30Z")) == ["billing-session"]
    assert "Runs 2-4 of 4" in await call(read, session_id="billing-session", start=1)
    assert await call(read, session_id="foreign-session") == "Session not found."


def test_summary_and_run_content_filters_validate_and_evaluate():
    for key in ("summary", "run_content"):
        with pytest.raises(ValueError):
            normalize_session_filter({"op": "EQ", "key": key, "value": "x"})

    summary = normalize_session_filter({"op": "CONTAINS", "key": "summary", "value": "EXPORT"})
    assert matches_session_filter({"summary": {"summary": "billing export"}}, summary)
    assert not matches_session_filter({"summary": None}, summary)

    content = normalize_session_filter({"op": "CONTAINS", "key": "run_content", "value": "denied"})
    session = {"runs": [{"input": {"input_content": "Access DENIED"}, "content": None}]}
    assert matches_session_filter(session, content)
    structured = {"runs": [{"content": {"status": "denied"}}]}
    assert matches_session_filter(structured, content)
    # EXISTS semantics: a session without runs is a plain non-match, so NOT matches it.
    negated = normalize_session_filter({"op": "NOT", "condition": content})
    assert matches_session_filter({"runs": None}, negated)
