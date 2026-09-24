"""The user partition on the database backend: keying, isolation, and the upgrade of older tables."""

import sqlite3

from sqlalchemy import inspect as sa_inspect

from agno.db.sqlite import SqliteDb
import pytest

from agno.fs import FileSystem, InvalidPathError, SchemaOutdatedError, UnsupportedOperationError
from agno.fs.db import DbFileSystem


def _db(tmp_path) -> SqliteDb:
    return SqliteDb(db_file=str(tmp_path / "fs.db"))


def test_partitions_are_invisible_to_each_other(tmp_path):
    fs = FileSystem(_db(tmp_path), namespace="notes")
    alice = fs.resolve(user_id="alice")
    bob = fs.resolve(user_id="bob")

    alice.write("a.md", "alice\n")
    bob.write("a.md", "bob\n")
    fs.write("a.md", "shared\n")

    assert alice.read("a.md") == "alice\n"
    assert bob.read("a.md") == "bob\n"
    assert fs.read("a.md") == "shared\n"
    assert alice.read_with_meta("a.md").meta.user_id == "alice"  # type: ignore[union-attr]
    assert fs.read_with_meta("a.md").meta.user_id is None  # type: ignore[union-attr]
    assert [m.user_id for m in alice.list()] == ["alice"]
    assert alice.search("bob") == []
    assert alice.usage().file_count == 1
    assert bob.delete("a.md") is True
    assert alice.read("a.md") == "alice\n"


def test_append_move_cas_and_contains_stay_in_the_partition(tmp_path):
    fs = FileSystem(_db(tmp_path), namespace="notes")
    alice = fs.resolve(user_id="alice")
    fs.write("log.md", "shared line\n")

    first = alice.append("log.md", "alice line")
    assert first.version == 1 and first.user_id == "alice"
    assert alice.read("log.md") == "alice line\n"
    assert fs.read("log.md") == "shared line\n"

    assert alice.contains(["alice line"]).found == ["alice line"]
    assert fs.contains(["alice line"]).missing == ["alice line"]

    alice.write("log.md", "v2\n", expected_version=first.version)
    assert alice.read("log.md") == "v2\n"
    moved = alice.move("log.md", "archive/log.md")
    assert moved.user_id == "alice"
    assert fs.read("log.md") == "shared line\n"
    assert alice.read("archive/log.md") == "v2\n"


def test_user_scoped_instance_fails_closed_without_a_user(tmp_path):
    fs = FileSystem(_db(tmp_path), namespace="diary", user_scoped=True)
    try:
        fs.write("a.md", "x\n")
    except InvalidPathError as e:
        assert "no user is bound" in str(e)
    else:
        raise AssertionError("expected InvalidPathError")
    assert fs.resolve(user_id="alice").write("a.md", "x\n").user_id == "alice"


def test_user_templated_namespace_isolates_by_name_not_partition(tmp_path):
    fs = FileSystem(_db(tmp_path), namespace="radar/{user_id}")
    bound = fs.resolve(user_id="alice")
    bound.write("a.md", "x\n")

    # The user is in the namespace, so the file sits in the shared partition of it:
    # exactly where data written before partitions existed already is.
    assert FileSystem(_db(tmp_path), namespace="radar/alice").read("a.md") == "x\n"
    assert bound.user_id == "alice"
    assert bound.list()[0].user_id is None


def test_outdated_table_is_refused_until_upgraded(tmp_path):
    db_file = tmp_path / "old.db"
    # A table exactly as DbFileSystem created it before the column existed.
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE agno_fs (namespace VARCHAR NOT NULL, path VARCHAR NOT NULL, content TEXT NOT NULL, "
            "size_bytes BIGINT NOT NULL, version BIGINT NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT, "
            "PRIMARY KEY (namespace, path))"
        )
        conn.executemany(
            "INSERT INTO agno_fs VALUES (?, ?, ?, 1, 3, 0, 0)",
            [("users/alice/notes", "a.md", "a"), ("shared", "d.md", "d")],
        )

    backend = DbFileSystem(db=SqliteDb(db_file=str(db_file)))
    # An outdated table is refused, never upgraded on the way to a statement.
    with pytest.raises(SchemaOutdatedError, match="upgrade_schema"):
        FileSystem(backend=backend, namespace="shared").read("d.md")
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("PRAGMA table_info(agno_fs)").fetchall()[-1][1] == "updated_at"

    assert backend.upgrade_schema() is True

    inspector = sa_inspect(backend.db_engine)
    columns = {column["name"]: column for column in inspector.get_columns("agno_fs")}
    assert columns["user_id"]["nullable"] is False
    assert set(inspector.get_pk_constraint("agno_fs")["constrained_columns"]) == {"namespace", "user_id", "path"}
    with sqlite3.connect(db_file) as conn:
        assert sorted(conn.execute("SELECT namespace, user_id, path, version FROM agno_fs").fetchall()) == [
            ("shared", "", "d.md", 3),
            ("users/alice/notes", "", "a.md", 3),
        ]

    # Rows keep their place: a custom users/{user_id}/... template still finds them.
    fs = FileSystem(backend=backend, namespace="users/{user_id}/notes").resolve(user_id="alice")
    assert fs.read("a.md") == "a"
    # And the upgraded table serves partitions like a fresh one.
    shared = FileSystem(backend=backend, namespace="shared")
    shared.resolve(user_id="bob").write("d.md", "bob\n")
    assert shared.read("d.md") == "d"

    # Idempotent: the upgrade finds a current table and changes nothing, and a fresh table needs none.
    assert DbFileSystem(db=SqliteDb(db_file=str(db_file))).upgrade_schema() is False
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM agno_fs").fetchone() == (3,)
    assert DbFileSystem(db=SqliteDb(db_file=str(tmp_path / "fresh.db"))).upgrade_schema() is False


def test_custom_backend_without_partitions_serves_the_shared_one_and_refuses_users(tmp_path):
    from typing import Dict, List, Optional

    from agno.fs.base import BaseFS
    from agno.fs.types import FileMeta

    class DictBackend(BaseFS):
        def __init__(self) -> None:
            self.files: Dict[str, str] = {}

        def read(self, namespace: str, path: str) -> Optional[str]:  # type: ignore[override]
            return self.files.get(f"{namespace}/{path}")

        def write(self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None):  # type: ignore[override]
            self.files[f"{namespace}/{path}"] = content
            return FileMeta(path=path, size_bytes=len(content))

        def list(self, namespace: str, directory: str = "") -> List[FileMeta]:  # type: ignore[override]
            return [FileMeta(path=k.split("/", 1)[1], size_bytes=len(v)) for k, v in self.files.items()]

        def delete(self, namespace: str, path: str) -> bool:  # type: ignore[override]
            return self.files.pop(f"{namespace}/{path}", None) is not None

    fs = FileSystem(backend=DictBackend(), namespace="ns")
    fs.write("a.md", "x\n")
    fs.append("a.md", "y")
    assert fs.read("a.md") == "x\ny\n"

    bound = fs.resolve(user_id="alice")
    try:
        bound.write("b.md", "z\n")
    except UnsupportedOperationError as e:
        assert "does not partition" in str(e)
    else:
        raise AssertionError("a backend without partitions must not silently share a user's write")
