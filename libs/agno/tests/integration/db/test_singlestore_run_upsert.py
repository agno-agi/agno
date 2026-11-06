import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from agno.db.singlestore import SingleStoreDb
from agno.db.utils import json_serializer
from agno.run.agent import RunOutput
from agno.session.agent import AgentSession


@pytest.fixture
def db() -> Iterator[SingleStoreDb]:
    url = os.environ.get("SINGLESTORE_TEST_URL")
    if not url:
        pytest.skip("Set SINGLESTORE_TEST_URL to run against SingleStore")
    suffix = uuid4().hex
    engine = create_engine(url, json_serializer=json_serializer)
    db = SingleStoreDb(
        db_engine=engine,
        session_table=f"test_sessions_{suffix}",
        runs_table=f"test_runs_{suffix}",
        versions_table=f"test_versions_{suffix}",
    )
    try:
        yield db
    finally:
        with db.db_engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {db.runs_table_name}"))
            connection.execute(text(f"DROP TABLE IF EXISTS {db.session_table_name}"))
            connection.execute(text(f"DROP TABLE IF EXISTS {db.versions_table_name}"))
        engine.dispose()


def test_run_can_be_saved_and_read_back(db: SingleStoreDb) -> None:
    db.upsert_run(
        RunOutput(agent_id="a1", run_id="first", session_id="s1", content={"answer": "hello"}), "s1", run_index=0
    )

    saved = db.get_run("first")
    assert isinstance(saved, RunOutput)
    assert saved.content == {"answer": "hello"}


def test_run_index_after_delete_and_update(db: SingleStoreDb) -> None:
    db.upsert_session(AgentSession(session_id="s1", agent_id="a1", created_at=1000, updated_at=1000))
    for index, run_id in enumerate(("r0", "r1", "r2")):
        db.upsert_run(RunOutput(agent_id="a1", run_id=run_id, session_id="s1"), "s1", run_index=index)
    db.upsert_run(RunOutput(agent_id="a1", run_id="other", session_id="s2"), "s2", run_index=100)
    db.delete_runs(["r0", "r1"])
    db.upsert_run(RunOutput(agent_id="a1", run_id="r3", session_id="s1"), "s1", run_index=1)
    db.upsert_run(RunOutput(agent_id="a1", run_id="r9", session_id="s1"), "s1", run_index=9)
    db.upsert_run(RunOutput(agent_id="a1", run_id="r10", session_id="s1"), "s1")
    db.upsert_run(RunOutput(agent_id="a1", run_id="r2", session_id="s1", content="updated"), "s1", run_index=50)

    with db.db_engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT run_id, run_index FROM {db.runs_table_name} WHERE session_id = 's1' ORDER BY run_index")
        ).all()
    assert rows == [("r2", 2), ("r3", 3), ("r9", 9), ("r10", 10)]
    session = db.get_session("s1")
    assert isinstance(session, AgentSession)
    assert [run.run_id for run in session.runs] == ["r2", "r3", "r9", "r10"]
    assert session.runs[0].content == "updated"

    with db.db_engine.begin() as connection:
        connection.execute(text(f"UPDATE {db.runs_table_name} SET run_index = NULL WHERE run_id = 'r2'"))
    db.upsert_run(RunOutput(agent_id="a1", run_id="r2", session_id="s1"), "s1")
    with db.db_engine.connect() as connection:
        index = connection.execute(text(f"SELECT run_index FROM {db.runs_table_name} WHERE run_id = 'r2'")).scalar_one()
    assert index == 11
