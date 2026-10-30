"""Projected session-run reads for the run-previews listing.

Previews read with ``get_session(run_preview=True)`` must equal the previews of the
full read path (same runs, order, classification, input fallbacks and truncation),
whether or not the adapter pushes the projection into its queries.
"""

import json
import time
from typing import Any, Dict, List, Optional, Union

import pytest
from sqlalchemy import text

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.db.in_memory import InMemoryDb
from agno.db.json import JsonDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.db.utils import RUN_PREVIEW_FIELDS
from agno.os.schema import SessionRunPreviewSchema
from agno.os.services.sessions import SessionNotFoundError, get_session_run_previews, get_session_runs
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession

LONG = "y" * 600


def _user(content: str) -> Dict[str, Any]:
    return {"role": "user", "content": content}


def _metrics() -> Dict[str, Any]:
    return {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}


def agent_session_dict(now: int) -> Dict[str, Any]:
    base = {"agent_id": "agent-1", "session_id": "s-agent", "user_id": "u1", "metrics": _metrics()}
    runs = [
        {
            **base,
            "run_id": "a-str",
            "status": "COMPLETED",
            "created_at": now - 50,
            "input": {"input_content": "hello " + LONG, "images": [{"id": "img-1", "url": "https://x/1.png"}]},
            "content": "answer " + LONG,
            "messages": [_user("hello " + LONG), {"role": "assistant", "content": "answer"}],
            "events": [{"event": "RunStarted"}],
        },
        {
            **base,
            "run_id": "a-structured",
            "status": "RUNNING",
            "created_at": now - 40,
            "input": {"input_content": {"question": "q", "detail": LONG}},
            "content": {"answer": 42, "notes": LONG},
            "content_type": "Answer",
            "messages": [_user("q")],
        },
        {
            **base,
            "run_id": "a-msg-list",
            "status": "PAUSED",
            "created_at": now - 30,
            "input": {"input_content": [_user("from message list")]},
            "messages": [_user("from message list")],
        },
        {
            # No stored input: the preview falls back to the last user message.
            **base,
            "run_id": "a-no-input",
            "status": "ERROR",
            "created_at": now - 20,
            "messages": [_user("first"), {"role": "assistant", "content": "x"}, _user("fallback " + LONG)],
        },
        {
            # Member run of another agent; must not be dropped or reclassified.
            **base,
            "agent_id": "agent-2",
            "run_id": "a-member",
            "parent_run_id": "a-str",
            "status": "COMPLETED",
            "created_at": now - 10,
            "input": {"input_content": "member input"},
            "content": "member output",
        },
    ]
    return {
        "session_id": "s-agent",
        "session_type": "agent",
        "agent_id": "agent-1",
        "user_id": "u1",
        "agent_data": {"name": "A", "agent_id": "agent-1"},
        "runs": runs,
        "created_at": now,
        "updated_at": now,
    }


def team_session_dict(now: int) -> Dict[str, Any]:
    runs = [
        {
            "run_id": "t-member",
            "agent_id": "member-1",
            "parent_run_id": "t-lead",
            "session_id": "s-team",
            "user_id": "u1",
            "status": "COMPLETED",
            "created_at": now - 30,
            "input": {"input_content": "member task"},
            "content": "member result",
            "metrics": _metrics(),
        },
        {
            "run_id": "t-lead",
            "team_id": "team-1",
            "session_id": "s-team",
            "user_id": "u1",
            "status": "COMPLETED",
            "created_at": now - 20,
            "input": {"input_content": "team task " + LONG},
            "content": {"summary": "done"},
            "content_type": "Summary",
            "messages": [_user("team task")],
            "metrics": _metrics(),
        },
    ]
    return {
        "session_id": "s-team",
        "session_type": "team",
        "team_id": "team-1",
        "user_id": "u1",
        "team_data": {"name": "T", "team_id": "team-1"},
        "runs": runs,
        "created_at": now,
        "updated_at": now,
    }


def workflow_session_dict(now: int) -> Dict[str, Any]:
    step_run = {
        "run_id": "w-step-agent",
        "agent_id": "step-agent",
        "session_id": "s-wf",
        "status": "COMPLETED",
        "created_at": now - 45,
        "input": {"input_content": "step input"},
        "messages": [_user("step input")],
        "content": "step output",
    }
    runs = [
        {
            "run_id": "w-str",
            "workflow_id": "wf-1",
            "session_id": "s-wf",
            "user_id": "u1",
            "status": "COMPLETED",
            "created_at": now - 40,
            "input": "workflow input " + LONG,
            "content": "workflow output",
            "step_executor_runs": [step_run],
            "step_results": [{"step_name": "s1", "content": LONG}],
        },
        {
            "run_id": "w-dict",
            "workflow_id": "wf-1",
            "session_id": "s-wf",
            "user_id": "u1",
            "status": "PENDING",
            "created_at": now - 30,
            "input": {"topic": "agents", "depth": 3},
            "content": {"report": LONG},
        },
        {
            # No stored input: preview falls back to the first step's user message.
            "run_id": "w-no-input",
            "workflow_id": "wf-1",
            "session_id": "s-wf",
            "user_id": "u1",
            "status": "CANCELLED",
            "created_at": now - 20,
            "step_executor_runs": [step_run],
        },
    ]
    return {
        "session_id": "s-wf",
        "session_type": "workflow",
        "workflow_id": "wf-1",
        "user_id": "u1",
        "workflow_data": {"name": "W"},
        "runs": runs,
        "created_at": now,
        "updated_at": now,
    }


def build_sessions(now: Optional[int] = None) -> List[Union[AgentSession, TeamSession, WorkflowSession]]:
    now = now or int(time.time())
    return [
        AgentSession.from_dict(agent_session_dict(now)),  # type: ignore[list-item]
        TeamSession.from_dict(team_session_dict(now)),  # type: ignore[list-item]
        WorkflowSession.from_dict(workflow_session_dict(now)),  # type: ignore[list-item]
    ]


async def _call(db: Union[BaseDb, AsyncBaseDb], name: str, **kwargs: Any) -> Any:
    result = getattr(db, name)(**kwargs)
    if isinstance(db, AsyncBaseDb):
        result = await result
    return result


async def seed(db: Union[BaseDb, AsyncBaseDb]) -> List[Any]:
    sessions = build_sessions()
    for session in sessions:
        await _call(db, "upsert_session", session=session)
        for idx, run in enumerate(session.runs or []):
            await _call(db, "upsert_run", run=run, session_id=session.session_id, user_id="u1", run_index=idx)
    return sessions


async def assert_preview_parity(
    db: Union[BaseDb, AsyncBaseDb],
    session_id: str,
    session_type: Optional[SessionType] = None,
    user_id: Optional[str] = None,
    created_after: Optional[int] = None,
    created_before: Optional[int] = None,
) -> List[SessionRunPreviewSchema]:
    kwargs: Dict[str, Any] = dict(
        session_id=session_id,
        session_type=session_type,
        user_id=user_id,
        created_after=created_after,
        created_before=created_before,
    )
    full = [SessionRunPreviewSchema.from_run(r) for r in await get_session_runs(db, **kwargs)]
    fast = await get_session_run_previews(db, **kwargs)
    assert [p.model_dump() for p in fast] == [p.model_dump() for p in full]
    return fast


async def check_backend(db: Union[BaseDb, AsyncBaseDb]) -> None:
    sessions = await seed(db)
    now = sessions[0].created_at
    for session in sessions:
        previews = await assert_preview_parity(db, session.session_id)
        assert previews, session.session_id

    # Caller-supplied type wins over the stored one, exactly as on the full path.
    await assert_preview_parity(db, "s-wf", session_type=SessionType.AGENT)
    await assert_preview_parity(db, "s-team", session_type=SessionType.TEAM, user_id="u1")
    await assert_preview_parity(db, "s-agent", created_after=now - 35, created_before=now - 15)

    previews = await get_session_run_previews(db, session_id="s-agent")
    by_id = {p.run_id: p for p in previews}
    assert by_id["a-no-input"].run_input == ("fallback " + LONG)[:280]
    # Structured content previews as truncated JSON (key order is the store's: JSONB sorts keys).
    assert (by_id["a-structured"].content_preview or "").startswith("{")
    assert len(by_id["a-structured"].content_preview or "") == 280
    assert by_id["a-member"].parent_run_id == "a-str"

    with pytest.raises(SessionNotFoundError):
        await get_session_run_previews(db, session_id="s-agent", user_id="someone-else")
    with pytest.raises(SessionNotFoundError):
        await get_session_run_previews(db, session_id="missing")


@pytest.fixture
def sqlite_db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "previews.db"))


@pytest.fixture
def async_sqlite_db(tmp_path):
    return AsyncSqliteDb(db_file=str(tmp_path / "previews_async.db"))


async def test_sqlite_previews_match_full_path(sqlite_db):
    await check_backend(sqlite_db)


async def test_async_sqlite_previews_match_full_path(async_sqlite_db):
    await check_backend(async_sqlite_db)


async def test_in_memory_previews_match_full_path():
    await check_backend(InMemoryDb())


async def test_json_previews_match_full_path(tmp_path):
    await check_backend(JsonDb(db_path=str(tmp_path / "json_db")))


async def test_sqlite_previews_merge_legacy_runs_blob(tmp_path):
    """A session still carrying the pre-v3 ``runs`` column merges it with the runs table."""
    db_file = str(tmp_path / "legacy.db")
    sqlite_db = SqliteDb(db_file=db_file)
    await seed(sqlite_db)
    blob = agent_session_dict(int(time.time()))["runs"]
    blob.append({**blob[0], "run_id": "legacy-only", "created_at": blob[0]["created_at"] - 100})
    sessions_table = sqlite_db._get_table(table_type="sessions")
    runs_table = sqlite_db._get_table(table_type="runs")
    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(text(f"ALTER TABLE {sessions_table.name} ADD COLUMN runs JSON"))
        sess.execute(
            text(f"UPDATE {sessions_table.name} SET runs = :runs WHERE session_id = 's-agent'"),
            {"runs": json.dumps([blob[-1], blob[0]])},
        )
        sess.execute(text(f"DELETE FROM {runs_table.name} WHERE run_id = 'a-structured'"))

    # A fresh instance reflects the re-added legacy column.
    previews = await assert_preview_parity(SqliteDb(db_file=db_file), "s-agent")
    assert previews[0].run_id == "legacy-only"
    assert "a-structured" not in {p.run_id for p in previews}


class _StatementLog:
    """Records SQL a SQLAlchemy engine sends, to prove ``run_data`` is never read whole."""

    def __init__(self, engine: Any):
        from sqlalchemy import event

        self.statements: List[str] = []
        target = getattr(engine, "sync_engine", engine)
        event.listen(target, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):  # noqa: ARG002
        self.statements.append(statement)

    def assert_run_data_projected(self) -> None:
        import re

        reads = [s for s in self.statements if s.lstrip().upper().startswith("SELECT")]
        assert reads, "expected the projected read to hit the database"
        for statement in reads:
            # Strip bind names and every JSON path read; any remaining mention is a whole-column read.
            stripped = re.sub(r"%\(run_data_\d+\)s|:run_data_\d+", "", statement)
            stripped = re.sub(r"(?i)(json_extract|json_type|json_unquote)\s*\(\s*[\w.\"`]*run_data", "", stripped)
            stripped = re.sub(r"[\w.\"`]*run_data\s*(->>?|#>>?)", "", stripped)
            stripped = re.sub(r"[\w.\"`]*run_data\s*\[", "", stripped)
            assert "run_data" not in stripped, statement


NO_INPUT_RUNS = {"a-no-input", "w-no-input"}
FALLBACK_KEYS = {"messages", "step_executor_runs"}


async def check_projected_query(db: Union[BaseDb, AsyncBaseDb], engine: Any) -> None:
    """get_session(run_preview=True) returns only RUN_PREVIEW_FIELDS, read key by key in SQL."""
    await seed(db)
    log = _StatementLog(engine)
    for session_id in ("s-agent", "s-team", "s-wf"):
        session = await _call(db, "get_session", session_id=session_id, deserialize=False, run_preview=True)
        for run in session["runs"]:
            allowed = set(RUN_PREVIEW_FIELDS) | (FALLBACK_KEYS if run["run_id"] in NO_INPUT_RUNS else set())
            assert set(run) <= allowed, (run["run_id"], sorted(set(run) - allowed))
            if run.get("workflow_id") is None and "input" in run:
                # Media sits beside input_content; only workflow runs preview their raw input.
                assert set(run["input"]) == {"input_content"}, run["run_id"]
    log.assert_run_data_projected()


async def test_sqlite_previews_are_projected_in_sql(sqlite_db):
    await check_projected_query(sqlite_db, sqlite_db.db_engine)


async def test_async_sqlite_previews_are_projected_in_sql(async_sqlite_db):
    await check_projected_query(async_sqlite_db, async_sqlite_db.db_engine)


async def test_run_preview_is_ignored_when_deserializing(sqlite_db):
    """A deserialized session can be saved back, so it must never carry partial runs."""
    await seed(sqlite_db)
    # A team session: agent sessions deserialize through the run-object cache instead.
    session = sqlite_db.get_session(session_id="s-team", run_preview=True)
    lead = next(run for run in session.runs if run.run_id == "t-lead")  # type: ignore[union-attr]
    assert lead.messages and lead.metrics


async def test_previews_need_no_per_run_reads(monkeypatch, sqlite_db):
    """Runs without stored input carry their fallback fields in the same projected read."""
    await seed(sqlite_db)

    def no_get_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("previews must not re-read runs one at a time")

    monkeypatch.setattr(sqlite_db, "get_run", no_get_run)
    for session_id in ("s-agent", "s-team", "s-wf"):
        await assert_preview_parity(sqlite_db, session_id)


async def test_previews_work_with_adapters_predating_run_preview():
    """A custom adapter whose get_session lacks the keyword still serves /run-previews (full read)."""

    class LegacySignatureDb(InMemoryDb):
        def get_session(self, session_id, session_type=None, user_id=None, deserialize=True, runs_limit=None):  # type: ignore[override]
            return super().get_session(
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=deserialize,
                runs_limit=runs_limit,
            )

    db = LegacySignatureDb()
    await seed(db)
    await assert_preview_parity(db, "s-agent")
