from dataclasses import fields

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.run.agent import RunOutput
from agno.sandbox.postgres import _RUNTIME_RUN_FIELDS


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
