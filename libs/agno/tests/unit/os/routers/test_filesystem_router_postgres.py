"""Filesystems declared on the AgentOS, stored in PostgreSQL.

Runs against the live pgvector container (localhost:5532) with unique schemas
per test; skips cleanly when psycopg or the server is absent.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

psycopg = pytest.importorskip("psycopg")

from agno.db.postgres import AsyncPostgresDb, PostgresDb  # noqa: E402
from agno.fs import FileSystem  # noqa: E402
from agno.fs.db import AsyncDbFileSystem, DbFileSystem  # noqa: E402
from agno.os import AgentOS  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
OS_ID = "filesystem-route-postgres-tests"


def _server_reachable() -> bool:
    # A raw probe, not an adapter call: adapter methods catch and log
    # connection errors, so they cannot signal an absent server.
    from sqlalchemy import create_engine, text

    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _postgres_server():
    if not _server_reachable():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")


@pytest.fixture
def db(_postgres_server):
    database = PostgresDb(id="pg-main", db_url=DB_URL)
    try:
        yield database
    finally:
        database.db_engine.dispose()


@pytest.fixture
def new_schema(db):
    """Names of schemas no other run uses. Each is dropped when the test ends."""
    from sqlalchemy import text

    created: list[str] = []

    def create() -> str:
        schema = f"fs_routes_{uuid.uuid4().hex[:8]}"
        created.append(schema)
        return schema

    yield create
    with db.Session() as sess, sess.begin():
        for schema in created:
            sess.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _client(*filesystems: FileSystem) -> TestClient:
    return TestClient(AgentOS(id=OS_ID, filesystem=list(filesystems)).get_app(), raise_server_exceptions=False)


def test_a_declared_filesystem_on_postgres_is_listed_and_read_by_id(db, new_schema):
    schema = new_schema()
    handbook = FileSystem(backend=DbFileSystem(db=db, db_schema=schema), namespace="handbook")
    handbook.write("guides/style.md", "plain words needle\n")

    with _client(handbook) as client:
        entries = client.get("/config").json()["filesystem"]["namespaces"]
        assert [
            (e["id"], e["declared"], e["agents"], e["backend_type"], e["db_id"], e["db_schema"], e["table_name"])
            for e in entries
        ] == [("handbook", True, [], "db", "pg-main", schema, "agno_fs")]

        by_id = {"filesystem_id": "handbook"}
        listed = client.get("/filesystem/entries", params=by_id)
        assert listed.status_code == 200
        assert [(entry["path"], entry["type"]) for entry in listed.json()["entries"]] == [("guides", "directory")]
        content = client.get("/filesystem/content", params={**by_id, "path": "guides/style.md"})
        assert content.json()["content"] == "plain words needle\n"
        search = client.get("/filesystem/search", params={**by_id, "query": "needle"})
        assert [entry["path"] for entry in search.json()["entries"]] == ["guides/style.md"]
        rows = client.get("/filesystem/files", params=by_id).json()["entries"]
        assert [(row["filesystem_id"], row["path"]) for row in rows] == [("handbook", "guides/style.md")]


def test_one_namespace_in_two_schemas_of_one_database_gets_two_ids(db, new_schema):
    current_schema, archive_schema = new_schema(), new_schema()
    current = FileSystem(backend=DbFileSystem(db=db, db_schema=current_schema), namespace="handbook")
    archive = FileSystem(backend=DbFileSystem(db=db, db_schema=archive_schema), namespace="handbook")
    current.write("style.md", "current\n")
    archive.write("style.md", "archive\n")

    with _client(current, archive) as client:
        ids = {e["db_schema"]: e["id"] for e in client.get("/config").json()["filesystem"]["namespaces"]}
        # One table name in two schemas is two stores, so each id names the schema.
        assert ids == {
            current_schema: f"handbook:pg-main:{current_schema}.agno_fs",
            archive_schema: f"handbook:pg-main:{archive_schema}.agno_fs",
        }
        for schema, expected in ((current_schema, "current\n"), (archive_schema, "archive\n")):
            content = client.get("/filesystem/content", params={"filesystem_id": ids[schema], "path": "style.md"})
            assert content.status_code == 200
            assert content.json()["content"] == expected
        ambiguous = client.get("/filesystem/content", params={"filesystem_id": "handbook", "path": "style.md"})
        assert ambiguous.status_code == 409


def test_a_declared_filesystem_on_async_postgres_is_browsable_on_every_route(db, new_schema):
    schema = new_schema()
    # Seeded through the synchronous backend, then served from the asynchronous one on the same table.
    FileSystem(backend=DbFileSystem(db=db, db_schema=schema), namespace="handbook").write(
        "guides/style.md", "plain words needle\n"
    )
    async_db = AsyncPostgresDb(id="pg-async", db_url=DB_URL)
    handbook = FileSystem(backend=AsyncDbFileSystem(async_db, db_schema=schema), namespace="handbook")

    with _client(handbook) as client:
        by_id = {"filesystem_id": "handbook"}
        listed = client.get("/filesystem/entries", params=by_id)
        assert listed.status_code == 200
        assert [(entry["path"], entry["type"]) for entry in listed.json()["entries"]] == [("guides", "directory")]
        content = client.get("/filesystem/content", params={**by_id, "path": "guides/style.md"})
        assert content.json()["content"] == "plain words needle\n"
        search = client.get("/filesystem/search", params={**by_id, "query": "needle"})
        assert [entry["path"] for entry in search.json()["entries"]] == ["guides/style.md"]
        rows = client.get("/filesystem/files", params=by_id).json()["entries"]
        assert [row["path"] for row in rows] == ["guides/style.md"]
