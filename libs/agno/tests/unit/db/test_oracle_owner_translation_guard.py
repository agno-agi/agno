"""Guard: no query OracleDb sends to the server ever carries a bare empty
string for an owner ("user_id") field.

This is the one deliberate exception to "assert on behavior, never on
generated SQL" (see the module docstring in
test_component_catalog_hardening_postgres.py for the sibling convention):
the failure this catches -- a single code path that reads or writes the
owner field without going through to_db_user_id/from_db_user_id -- produces
no exception. It silently lets Oracle fold "" to NULL, and NULL means every
owner, so a request scoped to the unowned bucket quietly becomes an
unfiltered read. Behavior-only testing cannot distinguish "correctly scoped"
from "accidentally unfiltered" here; only inspecting what was actually bound
to the database can.

The module skips cleanly when no Oracle server is reachable, per the
project's convention for live-server mirrors.
"""

import uuid

import pytest
from sqlalchemy import create_engine, event, text

from agno.db.oracle import OracleDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession

DB_URL = "oracle+oracledb://ai:ai@localhost:1523/?service_name=FREEPDB1"


def _server_reachable() -> bool:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1 from dual"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _oracle_server():
    if not _server_reachable():
        pytest.skip(f"Oracle server not reachable at {DB_URL}")


@pytest.fixture
def db(_oracle_server):
    suffix = uuid.uuid4().hex[:8]
    database = OracleDb(
        db_url=DB_URL,
        session_table=f"test_owner_sess_{suffix}",
        runs_table=f"test_owner_runs_{suffix}",
        memory_table=f"test_owner_mem_{suffix}",
        metrics_table=f"test_owner_metrics_{suffix}",
        knowledge_table=f"test_owner_knowledge_{suffix}",
        auth_tokens_table=f"test_owner_auth_{suffix}",
    )
    yield database
    database.Session.remove()
    with database.db_engine.begin() as conn:
        for t in (
            database.runs_table_name,
            database.session_table_name,
            database.memory_table_name,
            database.metrics_table_name,
            database.knowledge_table_name,
            database.auth_tokens_table_name,
        ):
            if database.table_exists(t):
                conn.execute(text(f"DROP TABLE {t} CASCADE CONSTRAINTS"))
    database.db_engine.dispose()


def _install_guard(engine):
    """Record every bound parameter whose key names an owner column.

    Returns the list the event listener appends to; the caller inspects it
    after running whatever scenario it wants covered.
    """
    violations: list = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        param_sets = parameters if executemany else [parameters]
        for params in param_sets:
            if params is None:
                continue
            items = params.items() if isinstance(params, dict) else enumerate(params)
            for key, value in items:
                key_name = str(key).lower()
                if "user_id" in key_name and value == "":
                    violations.append((statement, key, value))

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    return violations


def test_owner_field_never_sent_as_bare_empty_string(db):
    """Exercises every ticket 03/04/08 path that touches an owner field with
    the unowned-bucket value, and fails if any bound parameter reaches the
    driver as a bare "" instead of the translated sentinel.
    """
    violations = _install_guard(db.db_engine)

    # Sessions: an unowned session.
    session = AgentSession(session_id="owner-guard-session", agent_id="a", user_id="", created_at=1700000000)
    db.upsert_session(session)
    db.get_session("owner-guard-session")
    db.get_sessions(user_id="")
    db.rename_session("owner-guard-session", None, "renamed")
    db.delete_session("owner-guard-session")

    # Memories: an unowned memory.
    memory = UserMemory(memory="unowned memory", user_id="")
    saved = db.upsert_user_memory(memory)
    db.get_user_memory(saved.memory_id, user_id="")
    db.get_user_memories(user_id="")
    db.get_all_memory_topics(user_id="")
    db.delete_user_memory(saved.memory_id, user_id="")

    # Metrics: the unowned bucket is written through calculate_metrics via a
    # session with user_id=None (translated to "" internally by
    # calculate_date_metrics), and read back with user_id="".
    metrics_session = AgentSession(session_id="owner-guard-metrics", agent_id="a", user_id=None, created_at=1700000001)
    db.upsert_session(metrics_session, deserialize=False)
    db.calculate_metrics()
    db.get_metrics(user_id="")
    db.delete_session("owner-guard-metrics")

    # Auth tokens: an unowned token. user_id is NOT NULL on this table, so
    # Postgres itself already stores "" for the unowned case -- exactly the
    # value Oracle's empty-string-is-null folding would otherwise destroy.
    db.upsert_auth_token({"provider": "owner-guard", "user_id": "", "service": "oauth", "token_data": {"t": "1"}})
    db.get_auth_token("owner-guard", "", "oauth")
    db.delete_auth_token("owner-guard", "", "oauth")

    # Knowledge: intentionally NOT exercised with user_id="" -- knowledge's
    # owner column has no unowned-bucket convention (None means shared, per
    # its own schema comment), so "" is not a value that domain ever takes.
    knowledge = KnowledgeRow(name="doc", description="d", user_id=None)
    db.upsert_knowledge_content(knowledge)
    db.get_knowledge_contents(user_id=None)
    db.delete_knowledge_content(knowledge.id)

    assert not violations, (
        f"owner field reached the database as a bare empty string in {len(violations)} bind(s): {violations[:5]}"
    )

    # Cross-check the guard itself is not a no-op: deliberately bind "" for a
    # non-owner-like key and confirm the pattern-matcher would have caught an
    # owner-field violation shaped like it.
    with db.db_engine.connect() as conn:
        conn.execute(text("SELECT :probe_user_id AS x FROM dual"), {"probe_user_id": ""})
    assert any(v[1] == "probe_user_id" for v in violations), "the guard failed to catch its own positive control"
