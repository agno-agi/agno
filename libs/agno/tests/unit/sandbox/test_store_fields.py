from dataclasses import fields
from types import SimpleNamespace

import pytest

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.run.agent import RunOutput
from agno.sandbox.postgres import _RUNTIME_RUN_FIELDS


@pytest.mark.asyncio
async def test_sandbox_pending_run_keeps_queue_origin_before_claim(monkeypatch):
    from agno.sandbox import _harness

    class Store:
        row = None

        async def aprepare(self, row):
            self.row = row

    store = Store()
    monkeypatch.setattr(_harness, "coordinator", lambda agent: SimpleNamespace(store=store))
    agent = SimpleNamespace(get_id=lambda: "agent", name="agent")
    run = await _harness.aprepare_pending_run(agent, "run", "session", None, "input", queued=True)

    assert run.execution_origin == "queue"
    assert run.queue_attempt == 0
    assert store.row["execution_origin"] == "queue"
    assert store.row["queue_attempt"] == 0

    ordinary = await _harness.aprepare_pending_run(agent, "other", "session", None, "input")
    assert ordinary.execution_origin == "inline"
    assert ordinary.queue_attempt is None


def test_runtime_run_fields_exist_on_run_output():
    # A renamed RunOutput field would otherwise drop silently from every committed sandbox run.
    assert _RUNTIME_RUN_FIELDS <= {field.name for field in fields(RunOutput)}


def test_each_session_table_gets_its_own_default_bindings_table():
    url = "postgresql+psycopg://user:password@localhost:1/db"
    for adapter in (PostgresDb, AsyncPostgresDb):
        default = adapter(db_url=url)
        other = adapter(db_url=url, session_table="team_sessions")
        assert default.sandbox_table_name != other.sandbox_table_name
        assert adapter(db_url=url, sandbox_table="explicit").sandbox_table_name == "explicit"


def test_derived_bindings_table_names_fit_postgres_identifiers():
    url = "postgresql+psycopg://user:password@localhost:1/db"
    first = PostgresDb(db_url=url, session_table="s" * 60).sandbox_table_name
    second = PostgresDb(db_url=url, session_table="s" * 59 + "t").sandbox_table_name
    assert len(first.encode()) <= 63 and len(second.encode()) <= 63
    assert first != second
