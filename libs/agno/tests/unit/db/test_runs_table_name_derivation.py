"""Regression tests for the shared-db / mismatched-runs-table data-loss incident.

Since v3.0 runs live in a dedicated runs table with a foreign key
``<runs_table>.session_id -> <session_table>.session_id``. The FK target binds
at table-creation time to the creating db's ``session_table``.

The runs table used to default to the shared ``agno_runs`` regardless of
``session_table``. So two ``PostgresDb`` instances against the same database
with different ``session_table`` names would collide on one ``agno_runs`` whose
FK was locked to whichever instance created it first. Every run from the other
instance referenced a session_id absent from the referenced session table, the
insert violated the FK, and the failure was swallowed to a warning while
``run()`` still reported success -- silent data loss.

The fix: when ``session_table`` is customized but ``runs_table`` is not, the
runs table name is derived as ``f"{session_table}_runs"`` so each session table
owns its own correctly foreign-keyed runs table. These tests lock that in and
guard the two behaviors that must not regress: the plain default is unchanged,
and an explicit ``runs_table`` still wins.
"""

from __future__ import annotations

import pytest

from agno.db.postgres import PostgresDb

# A syntactically valid dsn that is never connected to -- construction resolves
# table names without opening a connection.
_DSN = "postgresql+psycopg://user:pass@localhost:5599/never_connected"


def test_default_session_table_keeps_default_runs_table():
    """The plain default is unchanged: agno_sessions -> agno_runs."""
    db = PostgresDb(db_url=_DSN)
    assert db.session_table_name == "agno_sessions"
    assert db.runs_table_name == "agno_runs"


def test_custom_session_table_derives_matching_runs_table():
    """A custom session_table (no runs_table) derives its own runs table.

    This is the fix: without it, this db would share ``agno_runs`` and lose
    every run to the FK violation.
    """
    db = PostgresDb(db_url=_DSN, session_table="team_sessions")
    assert db.session_table_name == "team_sessions"
    assert db.runs_table_name == "team_sessions_runs"


def test_explicit_runs_table_always_wins():
    """An explicitly passed runs_table overrides the derivation."""
    db = PostgresDb(db_url=_DSN, session_table="team_sessions", runs_table="explicit_runs")
    assert db.session_table_name == "team_sessions"
    assert db.runs_table_name == "explicit_runs"


def test_explicit_runs_table_wins_even_with_default_session_table():
    """A custom runs_table on the default session table is honored."""
    db = PostgresDb(db_url=_DSN, runs_table="my_runs")
    assert db.session_table_name == "agno_sessions"
    assert db.runs_table_name == "my_runs"


def test_explicit_default_session_table_name_keeps_default_runs_table():
    """Passing the default name explicitly must not derive 'agno_sessions_runs'."""
    db = PostgresDb(db_url=_DSN, session_table="agno_sessions")
    assert db.runs_table_name == "agno_runs"


def test_two_dbs_different_session_tables_get_distinct_runs_tables():
    """The core incident: two dbs, one database, different session tables ->
    distinct runs tables, so neither loses runs to the other's FK."""
    a = PostgresDb(db_url=_DSN)
    b = PostgresDb(db_url=_DSN, session_table="team_sessions")

    assert a.runs_table_name == "agno_runs"
    assert b.runs_table_name == "team_sessions_runs"
    assert a.runs_table_name != b.runs_table_name


@pytest.mark.parametrize(
    "session_table, expected_runs_table",
    [
        (None, "agno_runs"),
        ("agno_sessions", "agno_runs"),
        ("team_sessions", "team_sessions_runs"),
        ("chat_sessions", "chat_sessions_runs"),
        ("workflow_session", "workflow_session_runs"),
    ],
)
def test_runs_table_derivation_matrix(session_table, expected_runs_table):
    kwargs = {"db_url": _DSN}
    if session_table is not None:
        kwargs["session_table"] = session_table
    db = PostgresDb(**kwargs)
    assert db.runs_table_name == expected_runs_table
