"""Decision lookups and outcome updates must not depend on listing recency."""

from pathlib import Path
from typing import AsyncIterator, Union

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.learn.config import DecisionLogConfig
from agno.learn.schemas import DecisionLog
from agno.learn.stores.decision_log import DecisionLogStore


def _decision(index: int) -> DecisionLog:
    return DecisionLog(
        id=f"decision-{index}",
        decision=f"Chose option {index}",
        user_id="user-1",
        agent_id="agent-1",
        session_id="session-1",
        team_id="team-1",
    )


def _assert_updated(decision: DecisionLog) -> None:
    assert decision.outcome == "Worked as expected"
    assert decision.outcome_quality == "good"
    assert decision.user_id == "user-1"
    assert decision.agent_id == "agent-1"
    assert decision.session_id == "session-1"
    assert decision.team_id == "team-1"


def test_get_and_update_outcome_beyond_latest_hundred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = SqliteDb(db_file=str(tmp_path / "decisions.db"))
    store = DecisionLogStore(config=DecisionLogConfig(db=db))
    try:
        with monkeypatch.context() as patch:
            for index in range(101):
                patch.setattr("time.time", lambda: 1000 + index)
                store.save(_decision(index))

        recent = db.get_learnings(learning_type="decision_log", limit=100)
        assert len(recent) == 100
        assert all(row["learning_id"] != "decision-0" for row in recent)
        assert store.get("decision-0") == _decision(0)
        assert store.update_outcome("decision-0", "Worked as expected", "good")
        updated = store.get("decision-0")
        assert updated is not None
        _assert_updated(updated)
    finally:
        db.db_engine.dispose()


@pytest.fixture(params=[SqliteDb, AsyncSqliteDb], ids=["sync-db", "async-db"])
async def db(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Union[SqliteDb, AsyncSqliteDb]]:
    database = request.param(db_file=str(tmp_path / "decisions.db"))
    yield database
    if isinstance(database, AsyncSqliteDb):
        await database.db_engine.dispose()
    else:
        database.db_engine.dispose()


async def test_aget_and_update_outcome_beyond_latest_hundred(
    db: Union[SqliteDb, AsyncSqliteDb], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = DecisionLogStore(config=DecisionLogConfig(db=db))
    with monkeypatch.context() as patch:
        for index in range(101):
            patch.setattr("time.time", lambda: 1000 + index)
            await store.asave(_decision(index))

    assert await store.aget("decision-0") == _decision(0)
    assert await store.aupdate_outcome("decision-0", "Worked as expected", "good")
    updated = await store.aget("decision-0")
    assert updated is not None
    _assert_updated(updated)


@pytest.mark.parametrize("learning_type", ["user_memory", "decision_log"])
async def test_rejects_other_learning_types_and_mismatched_content_ids(
    db: Union[SqliteDb, AsyncSqliteDb], learning_type: str
) -> None:
    store = DecisionLogStore(config=DecisionLogConfig(db=db))
    # A valid DecisionLog-shaped payload is insufficient: the row must be a
    # decision log, and its content ID must identify the requested decision.
    content_id = "requested" if learning_type == "user_memory" else "another-decision"
    content = DecisionLog(id=content_id, decision="Unrelated record").to_dict()
    if isinstance(db, AsyncSqliteDb):
        await db.upsert_learning(id="requested", learning_type=learning_type, content=content)
    else:
        db.upsert_learning(id="requested", learning_type=learning_type, content=content)
        assert store.get("requested") is None
        assert store.update_outcome("requested", "Wrong record") is False

    assert await store.aget("requested") is None
    assert await store.aupdate_outcome("requested", "Wrong record") is False
    if isinstance(db, AsyncSqliteDb):
        row = await db.get_learning_by_id("requested")
    else:
        row = db.get_learning_by_id("requested")
    assert row is not None
    assert row["content"] == content


async def test_missing_decision_is_not_created(db: Union[SqliteDb, AsyncSqliteDb]) -> None:
    store = DecisionLogStore(config=DecisionLogConfig(db=db))
    if isinstance(db, SqliteDb):
        assert store.get("missing") is None
        assert store.update_outcome("missing", "Unknown") is False
    assert await store.aget("missing") is None
    assert await store.aupdate_outcome("missing", "Unknown") is False
