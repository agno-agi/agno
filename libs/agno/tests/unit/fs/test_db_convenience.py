"""Shared database constructor compatibility without opening PostgreSQL connections."""

from copy import deepcopy

import pytest
from sqlalchemy import create_engine

from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.knowledge.embedder import Embedder
from agno.vectordb.pgvector import PgVector


@pytest.mark.asyncio
async def test_filesystem_database_alias(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "files.db"))
    fs = FileSystem(db=db, namespace="docs")
    fs.write("one.md", "one")
    assert FileSystem(db, "docs").read("one.md") == "one"
    await fs.awrite("two.md", "two")
    assert await FileSystem(backend=db, namespace="docs").aread("two.md") == "two"
    assert fs.backend.db_engine is db.db_engine


def test_filesystem_sources_and_resolution(tmp_path):
    backend = LocalFileSystem(root=tmp_path)
    fs = FileSystem(backend, "docs/{user_id}", max_file_bytes=123)
    assert fs.resolve(user_id="alice").backend is backend
    assert fs.resolve(user_id="alice").max_file_bytes == 123
    for kwargs in ({}, {"db": None}, {"backend": backend, "db": backend}, {"db": backend}, {"db": "sqlite://"}):
        with pytest.raises(ValueError):
            FileSystem(**kwargs)
    assert FileSystem(backend=backend, db=None).backend is backend


def test_pgvector_borrows_engine_and_preserves_identity():
    engine = create_engine("postgresql+psycopg://user:private@localhost/example")
    db = PostgresDb(db_engine=engine, db_schema="sessions")
    embedder = Embedder(dimensions=3)
    vector = PgVector("vectors", db=db, embedder=embedder)
    legacy = PgVector("vectors", db_engine=engine, embedder=embedder)
    assert vector.db_engine is engine
    assert vector.id == legacy.id
    assert vector.db_url is None
    assert vector.Session.session_factory.kw["bind"] is engine
    assert vector.schema == "ai"
    assert deepcopy(vector).db_engine is engine
    for kwargs in ({"db_url": str(engine.url)}, {"db_engine": engine}, {"db_url": "url", "db_engine": engine}):
        with pytest.raises(ValueError):
            PgVector("vectors", db=db, embedder=embedder, **kwargs)
    for invalid in (engine, str(engine.url), SqliteDb(), object()):
        with pytest.raises(ValueError, match="synchronous PostgresDb"):
            PgVector("vectors", db=invalid, embedder=embedder)
    engine.dispose()


def test_filesystem_import_and_custom_backend_need_no_sql_packages(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc, sys, tempfile
class NoSql(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in ('sqlalchemy', 'psycopg', 'pgvector'):
            raise ImportError('SQL dependencies deliberately unavailable')
sys.meta_path.insert(0, NoSql())
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
with tempfile.TemporaryDirectory() as root:
    backend = LocalFileSystem(root=root)
    fs = FileSystem(backend=backend)
    fs.write('test.md', 'ok')
    assert fs.read('test.md') == 'ok' and fs.backend is backend
""",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
