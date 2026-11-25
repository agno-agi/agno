"""Migration v3.3.0 on a 3.2.0 database: the Company files move with the Company tables.

The database is written in the shape agno 3.2.0 creates, with the files 3.2.0 stores, and is
migrated through MigrationManager. Runs on SQLite and PostgreSQL, sync and async; the PostgreSQL
cases use the live pgvector container and skip without it.
"""

from typing import Any, Dict, Tuple

import httpx
import pytest
from sqlalchemy import select

from agno.company.filesystem import company_filesystem
from agno.db.migrations.manager import MigrationManager
from agno.fs import FileSystem
from agno.os import AgentOS, CompanyConfig
from tests.unit.db.test_v3_3_0_company_goals_migration import (  # noqa: F401
    BACKLOG_TASK,
    GOAL,
    _call,
    _write_3_2_0,
    database,
    databases,
    postgres_available,
)


def _rows(db: Any) -> Dict[Tuple[str, str], Tuple[Any, ...]]:
    """Every row of the file table: (namespace, path) -> (content, version, created_at, updated_at, size)."""
    backend = FileSystem(db, namespace="company", user_scoped=False).backend
    table = backend.table
    with backend.db_engine.connect() as conn:
        found = conn.execute(
            select(
                table.c.namespace,
                table.c.path,
                table.c.content,
                table.c.version,
                table.c.created_at,
                table.c.updated_at,
                table.c.size_bytes,
            )
        ).all()
    return {(row[0], row[1]): tuple(row[2:]) for row in found}


def _write_files_3_2_0(db: Any) -> None:
    """Files in the namespaces 3.2.0 keeps them in, beside the ones the Company fixture writes."""

    def write(namespace: str, path: str, *contents: str) -> None:
        files = FileSystem(db, namespace=namespace, user_scoped=False)
        for content in contents:
            files.write(path, content)

    write("company/wiki", "brief.md", "# Company\n\nWe ship.\n", "# Company\n\nWe ship weekly.\n")
    write("company/wiki", "people/ada.md", "Ada leads docs.\n")
    write(f"company/products/{GOAL}/wiki", "brief.md", "# This AgentOS\n\nKeep it running.\n")
    write(f"company/products/{GOAL}/wiki", "status.md", "# Status\n\nGreen.\n", "# Status\n\nGreen, twice.\n")
    write(f"company/tasks/{BACKLOG_TASK}", "report.md", "The report\n")
    write(f"company/tasks/{BACKLOG_TASK}", "drafts/v1.md", "Draft\n")
    write("company/notes", "ideas.md", "A note\n", "A better note\n")


async def test_the_migration_moves_the_files_of_a_3_2_0_database(database):  # noqa: F811
    _write_3_2_0(database)
    reader = database.sync_db()
    _write_files_3_2_0(reader)
    before = _rows(reader)
    goal_files = database.files_goal
    assert (f"company/products/{goal_files}/wiki", "research.md") in before

    await MigrationManager(database.db()).up()

    after = _rows(reader)
    moved = {
        ("company/wiki", "brief.md"): "wiki/brief.md",
        ("company/wiki", "people/ada.md"): "wiki/people/ada.md",
        (f"company/products/{GOAL}/wiki", "brief.md"): f"goals/{GOAL}/brief.md",
        (f"company/products/{GOAL}/wiki", "status.md"): f"goals/{GOAL}/status.md",
        (f"company/products/{goal_files}/wiki", "research.md"): f"goals/{goal_files}/research.md",
        (f"company/tasks/{BACKLOG_TASK}", "report.md"): f"tasks/{BACKLOG_TASK}/report.md",
        (f"company/tasks/{BACKLOG_TASK}", "drafts/v1.md"): f"tasks/{BACKLOG_TASK}/drafts/v1.md",
        ("company/notes", "ideas.md"): "notes/ideas.md",
    }
    # Every file is at its tree path with the content, version and timestamps it had.
    for old, path in moved.items():
        assert after[("company", path)] == before[old], path
        assert old not in after
    assert after[("company", "wiki/brief.md")][:2] == ("# Company\n\nWe ship weekly.\n", 2)
    # Nothing is left in a namespace of the tree. The summary state is not part of the tree.
    left = {namespace for namespace, _ in after} - {"company"}
    assert left == {f"company/products/{goal_files}/summary-state"}
    assert len(after) == len(before)

    # A second run moves nothing.
    await MigrationManager(database.db()).up(force=True)
    assert _rows(reader) == after


async def test_a_migrated_3_2_0_database_serves_every_file_through_the_company_routes(database):  # noqa: F811
    _write_3_2_0(database)
    reader = database.sync_db()
    _write_files_3_2_0(reader)
    db = database.db()
    await MigrationManager(db).up()

    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agentos") as client:

        async def content(url: str) -> str:
            response = await client.get(url)
            assert response.status_code == 200, (url, response.text)
            return response.json()["content"]

        async def listed(url: str) -> list:
            response = await client.get(url, params={"limit": 100})
            assert response.status_code == 200, (url, response.text)
            return sorted(row["path"] for row in response.json()["data"])

        assert await content("/company/wiki/brief.md") == "# Company\n\nWe ship weekly.\n"
        assert await content("/company/wiki/people/ada.md") == "Ada leads docs.\n"
        assert "people/ada.md" in await listed("/company/wiki")
        assert await content(f"/company/goals/{GOAL}/wiki/brief.md") == "# This AgentOS\n\nKeep it running.\n"
        assert await content(f"/company/goals/{GOAL}/wiki/status.md") == "# Status\n\nGreen, twice.\n"
        assert await content(f"/company/goals/{database.files_goal}/wiki/research.md") == (
            "# Research\n\nFound on 3.2.0.\n"
        )
        assert await listed(f"/company/tasks/{BACKLOG_TASK}/files") == ["drafts/v1.md", "report.md"]
        assert await content(f"/company/tasks/{BACKLOG_TASK}/files/report.md") == "The report\n"
        assert await content(f"/company/tasks/{BACKLOG_TASK}/files/drafts/v1.md") == "Draft\n"
        assert await listed("/company/notes") == ["ideas.md"]
        assert await content("/company/notes/ideas.md") == "A better note\n"
        # A page keeps its version: a save with the version from before the upgrade is refused.
        stale = await client.put(
            f"/company/goals/{GOAL}/wiki/status.md", json={"content": "late", "expected_version": 1}
        )
        assert stale.status_code == 409, stale.text
        saved = await client.put(
            f"/company/goals/{GOAL}/wiki/status.md", json={"content": "next", "expected_version": 2}
        )
        assert saved.status_code == 200, saved.text
    assert company_filesystem(reader).read(f"goals/{GOAL}/status.md") == "next"


async def test_a_file_that_cannot_move_stops_the_migration_and_the_next_run_finishes(database):  # noqa: F811
    from agno.db.migrations.versions.v3_3_0 import CompanyFilesMigrationError

    _write_3_2_0(database)
    reader = database.sync_db()
    _write_files_3_2_0(reader)
    # A different note is already stored at the path the 3.2.0 note moves to.
    company_filesystem(reader).write("notes/ideas.md", "Written on 3.3.0\n")
    files_before, tables_before = _rows(reader), database.describe()

    try:
        await MigrationManager(database.db()).up()
        raise AssertionError("the migration did not stop")
    except CompanyFilesMigrationError as stopped:
        assert "notes/ideas.md" in str(stopped)

    # No file moved, on either database.
    assert _rows(reader) == files_before
    if database.postgres:
        # PostgreSQL renames the tables and moves the files in one transaction: the database is as it was.
        assert database.describe() == tables_before

    # With the newer note out of the way, the next run renames what is left and moves every file.
    company_filesystem(reader).delete("notes/ideas.md")
    await MigrationManager(database.db()).up()
    after = _rows(reader)
    assert after[("company", "notes/ideas.md")] == files_before[("company/notes", "ideas.md")]
    assert after[("company", f"goals/{GOAL}/status.md")] == files_before[(f"company/products/{GOAL}/wiki", "status.md")]
    assert {namespace for namespace, _ in after} == {
        "company",
        f"company/products/{database.files_goal}/summary-state",
    }
    assert "agno_company_goals" in database.describe(rows=False) and "agno_company_products" not in database.describe(
        rows=False
    )


async def test_a_database_with_notes_and_no_company_tables_gets_its_notes_moved(database):  # noqa: F811
    # An AgentOS without Company on 3.2.0: Super Agent's notes, and no Company table.
    reader = database.sync_db()
    notes = FileSystem(reader, namespace="company/notes", user_scoped=False)
    notes.write("ideas.md", "A note\n")
    notes.write("ideas.md", "A better note\n")
    FileSystem(reader, namespace="default", user_scoped=False).write("keep.md", "An agent's own file\n")
    before = _rows(reader)

    await MigrationManager(database.db()).up()

    after = _rows(reader)
    assert after[("company", "notes/ideas.md")] == before[("company/notes", "ideas.md")]
    assert after[("default", "keep.md")] == before[("default", "keep.md")]
    assert len(after) == 2
    # No Company table was made on the way.
    assert not [name for name in database.describe(rows=False) if name.startswith("agno_company")]


# ------------------------------------------------------------------ files behind a current stamp

COMPANY_TABLE_TYPES = ("goals", "sources", "projects", "tasks")


async def test_stamped_tables_do_not_hide_files_left_by_a_run_that_stopped(database):  # noqa: F811
    from agno.db.migrations.versions.v3_3_0 import CompanyFilesMigrationError

    _write_3_2_0(database)
    reader = database.sync_db()
    _write_files_3_2_0(reader)
    # The Company tables are stamped current before they are renamed.
    for name in COMPANY_TABLE_TYPES:
        await _call(database.db().upsert_schema_version, f"agno_company_{name}", "3.3.0")
    # A different note is already stored at the path the 3.2.0 note moves to.
    company_filesystem(reader).write("notes/ideas.md", "Written on 3.3.0\n")
    files_before = _rows(reader)

    with pytest.raises(CompanyFilesMigrationError, match="notes/ideas.md"):
        await MigrationManager(database.db()).up()

    # No file moved. SQLite keeps the table rename of the run that stopped; PostgreSQL keeps nothing.
    assert _rows(reader) == files_before
    renamed = "agno_company_goals" in database.describe(rows=False)
    assert renamed is not database.postgres
    assert {database.versions()[f"agno_company_{name}"] for name in COMPANY_TABLE_TYPES[1:]} == {"3.3.0"}

    # With the newer note out of the way, a plain run moves every file, whatever the stamps say.
    company_filesystem(reader).delete("notes/ideas.md")
    await MigrationManager(database.db()).up()

    after = _rows(reader)
    assert after[("company", "wiki/brief.md")] == files_before[("company/wiki", "brief.md")]
    assert after[("company", f"goals/{GOAL}/status.md")] == files_before[(f"company/products/{GOAL}/wiki", "status.md")]
    assert (
        after[("company", f"tasks/{BACKLOG_TASK}/report.md")]
        == files_before[(f"company/tasks/{BACKLOG_TASK}", "report.md")]
    )
    assert after[("company", "notes/ideas.md")] == files_before[("company/notes", "ideas.md")]
    assert {namespace for namespace, _ in after} == {
        "company",
        f"company/products/{database.files_goal}/summary-state",
    }
    tables = database.describe(rows=False)
    assert "agno_company_goals" in tables and "agno_company_products" not in tables


async def test_company_tables_created_before_the_migration_do_not_hide_the_notes(database):  # noqa: F811
    # An AgentOS without Company on 3.2.0 kept Super Agent's notes.
    reader = database.sync_db()
    notes = FileSystem(reader, namespace="company/notes", user_scoped=False)
    notes.write("ideas.md", "A note\n")
    notes.write("ideas.md", "A better note\n")
    FileSystem(reader, namespace="default", user_scoped=False).write("keep.md", "An agent's own file\n")
    before = _rows(reader)
    # On 3.3.0 Company is turned on and used before the migration runs: each Company table is created
    # on its first use and stamped current.
    db = database.db()
    for table_type in COMPANY_TABLE_TYPES:
        await _call(db._get_table, table_type, create_table_if_not_found=True)
    assert {database.versions()[f"agno_company_{name}"] for name in COMPANY_TABLE_TYPES} == {"3.3.0"}
    assert _rows(reader) == before

    await MigrationManager(database.db()).up()

    after = _rows(reader)
    assert after[("company", "notes/ideas.md")] == before[("company/notes", "ideas.md")]
    assert after[("company", "notes/ideas.md")][:2] == ("A better note\n", 2)
    assert after[("default", "keep.md")] == before[("default", "keep.md")]
    assert len(after) == 2
    assert {database.versions()[f"agno_company_{name}"] for name in COMPANY_TABLE_TYPES} == {"3.3.0"}
