"""Semantics tests for DbFileSystem (spec D4/D6/D9/D13), both dialects."""

import asyncio
import os

import pytest
from sqlalchemy import create_engine, text

from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.db import DEFAULT_DB_SCHEMA, DbFileSystem
from agno.fs.errors import QuotaExceededError, VersionConflictError

NS = "sem"


class TestMembershipPredicate:
    def test_superstring_no_false_positive(self, db_fs):
        db_fs.append(NS, "seen/log.md", "example.com/ab")
        assert db_fs.contains(NS, ["example.com/a"]) == set()
        assert db_fs.contains(NS, ["example.com/ab"]) == {"example.com/ab"}

    def test_percent_and_underscore_metachars(self, db_fs):
        db_fs.append(NS, "seen/log.md", "50%off\na_b\n")
        found = db_fs.contains(NS, ["50%off", "a_b", "50Xoff", "aXb", "50%%off"])
        assert found == {"50%off", "a_b"}

    def test_last_line_without_trailing_newline(self, db_fs):
        db_fs.write(NS, "raw.md", "first\nlast-no-newline")
        assert db_fs.contains(NS, ["last-no-newline"]) == {"last-no-newline"}
        assert db_fs.contains(NS, ["first"]) == {"first"}

    def test_cross_partition_via_directory_scope(self, db_fs):
        db_fs.append(NS, "seen/2026-07-23.md", "url-a")
        db_fs.append(NS, "seen/2026-07-24.md", "url-b")
        db_fs.append(NS, "notes/other.md", "url-c")
        found = db_fs.contains(NS, ["url-a", "url-b", "url-c"], directory="seen")
        assert found == {"url-a", "url-b"}

    def test_directory_autoescape_on_db_backend(self, db_fs):
        # The house convention in db/ is unescaped .like() — this pins the
        # opposite: directory rendering must autoescape (spec D6).
        db_fs.append(NS, "seen_urls/a.md", "in-underscore-dir")
        db_fs.append(NS, "seen-urls/b.md", "in-dash-dir")
        db_fs.append(NS, "50%off/c.md", "in-percent-dir")
        db_fs.append(NS, "50-EVERYTHING-off/d.md", "in-decoy-dir")
        assert db_fs.contains(NS, ["in-dash-dir"], directory="seen_urls") == set()
        assert {m.path for m in db_fs.list(NS, "seen_urls")} == {"seen_urls/a.md"}
        assert {m.path for m in db_fs.list(NS, "50%off")} == {"50%off/c.md"}
        assert db_fs.contains(NS, ["in-decoy-dir"], directory="50%off") == set()

    def test_round_trip_dedupe_regression(self, db_fs):
        # append("  a\r\nb  \r\n") then contains(["  a", "b  "]) — spec D13.
        fs = FileSystem(backend=db_fs, namespace="roundtrip")
        fs.append("seen/2026-07-24.md", "  a\r\nb  \r\n")
        result = fs.contains(["  a", "b  "], directory="seen")
        assert result.found == ["  a", "b  "]
        assert result.missing == []

    def test_u2028_round_trip(self, db_fs):
        # A splitlines() split would store two rows and return missing forever.
        fs = FileSystem(backend=db_fs, namespace="roundtrip")
        fs.append("seen/log.md", "a\u2028b\n")
        assert fs.read("seen/log.md") == "a\u2028b\n"
        assert fs.contains(["a\u2028b"]).found == ["a\u2028b"]

    def test_list_sorted_by_path_segments(self, db_fs):
        # Neither the Postgres ORDER BY order nor the raw-string order (spec D2/D13).
        fs = FileSystem(backend=db_fs, namespace="sorting")
        fs.write("seen/a.md", "1")
        fs.write("seen.md", "2")
        fs.write("seen-old/a.md", "3")
        assert [m.path for m in fs.list()] == ["seen/a.md", "seen-old/a.md", "seen.md"]


class TestSearchCaseFolding:
    def test_non_ascii_query_finds_lowercase(self, db_fs):
        # "Ü" finds "ü": identical behavior on the Postgres ILIKE prefilter and
        # the SQLite full Python scan (spec D9/D13).
        db_fs.write(NS, "notes/muc.md", "wir fahren nach münchen")
        matches = db_fs.search(NS, "MÜNCHEN")
        assert [m.path for m in matches] == ["notes/muc.md"]
        assert "münchen" in matches[0].snippet

    def test_ascii_case_insensitive(self, db_fs):
        db_fs.write(NS, "a.md", "Hello World")
        assert len(db_fs.search(NS, "hello")) == 1

    def test_metachars_in_query_do_not_wildcard(self, db_fs):
        db_fs.write(NS, "a.md", "100% sure")
        db_fs.write(NS, "b.md", "100x sure")
        matches = db_fs.search(NS, "100% sure")
        assert [m.path for m in matches] == ["a.md"]


class TestMove:
    def test_move_basic(self, db_fs):
        db_fs.write(NS, "a.md", "x")
        meta = db_fs.move(NS, "a.md", "b/c.md")
        assert meta.path == "b/c.md"
        assert meta.version == 2
        assert db_fs.read(NS, "a.md") is None
        assert db_fs.read(NS, "b/c.md") == "x"

    def test_move_dst_exists_refused(self, db_fs):
        db_fs.write(NS, "a.md", "x")
        db_fs.write(NS, "b.md", "y")
        with pytest.raises(FileExistsError):
            db_fs.move(NS, "a.md", "b.md")
        assert db_fs.read(NS, "a.md") == "x"
        assert db_fs.read(NS, "b.md") == "y"

    def test_move_overwrite(self, db_fs):
        db_fs.write(NS, "a.md", "x")
        db_fs.write(NS, "b.md", "y")
        db_fs.move(NS, "a.md", "b.md", overwrite=True)
        assert db_fs.read(NS, "b.md") == "x"
        assert db_fs.read(NS, "a.md") is None
        # Exactly one row for dst: a DELETE+UPDATE escaping its transaction
        # would leave both or neither (spec D13).
        assert [m.path for m in db_fs.list(NS)] == ["b.md"]

    def test_move_missing_src_with_overwrite_rolls_back_the_dst_delete(self, db_fs):
        """overwrite=True deletes dst first, then the UPDATE finds src missing. The
        rollback must put dst back; test_move_missing_src only covers overwrite=False,
        so this path was never exercised (PR review)."""
        db_fs.write(NS, "dst.md", "keep-me")
        with pytest.raises(FileNotFoundError):
            db_fs.move(NS, "ghost.md", "dst.md", overwrite=True)
        assert db_fs.read(NS, "dst.md") == "keep-me"
        assert [m.path for m in db_fs.list(NS)] == ["dst.md"]

    def test_move_missing_src(self, db_fs):
        with pytest.raises(FileNotFoundError):
            db_fs.move(NS, "ghost.md", "b.md")

    def test_collision_does_not_poison_follow_up_statements(self, db_fs):
        """A move collision raises IntegrityError inside a SAVEPOINT; on Postgres
        an unwrapped IntegrityError would leave the connection in
        InFailedSqlTransaction and every follow-up statement would fail
        (spec D9). SQLite hides this, so the test runs on both dialects."""
        db_fs.write(NS, "a.md", "x")
        db_fs.write(NS, "b.md", "y")
        with pytest.raises(FileExistsError):
            db_fs.move(NS, "a.md", "b.md")
        # Follow-up statements on the same engine/pool must work.
        assert db_fs.read(NS, "a.md") == "x"
        db_fs.write(NS, "c.md", "z")
        assert db_fs.read(NS, "c.md") == "z"
        assert db_fs.delete(NS, "c.md") is True


class TestConstruction:
    def test_dialect_rejection_mysql_url(self):
        with pytest.raises(ValueError):
            DbFileSystem(db_url="mysql://user:pass@localhost/db")

    def test_requires_exactly_one_source(self, tmp_path):
        with pytest.raises(ValueError):
            DbFileSystem()
        with pytest.raises(ValueError):
            DbFileSystem(db=SqliteDb(db_file=f"{tmp_path}/a.db"), db_url=f"sqlite:///{tmp_path}/b.db")

    def test_agno_db_constructor_shares_the_engine(self, tmp_path):
        # An agno db the caller already configured: the agent's files land beside
        # its sessions in one database, with one connection setup.
        agno_db = SqliteDb(db_file=f"{tmp_path}/app.db")
        fs = DbFileSystem(db=agno_db)
        assert fs.db_engine is agno_db.db_engine
        fs.write("ns", "a.md", "x")
        assert fs.read("ns", "a.md") == "x"
        # The agno db's own tables and the filesystem table coexist.
        assert DbFileSystem(db=agno_db).read("ns", "a.md") == "x"

    def test_files_get_their_own_schema_not_the_platform_one(self):
        # The filesystem is a tool component, not platform state: its table lives
        # in its own schema, independent of the db's (spec D4).
        pg = "postgresql+psycopg://ai:ai@localhost:5532/ai"
        assert DbFileSystem(db=PostgresDb(db_url=pg)).db_schema == DEFAULT_DB_SCHEMA == "fs"
        assert DbFileSystem(db=PostgresDb(db_url=pg, db_schema="myapp")).db_schema == "fs"
        assert DbFileSystem(db=PostgresDb(db_url=pg), db_schema="other").db_schema == "other"
        # SQLite has no schemas.
        assert DbFileSystem(db_url="sqlite://").db_schema is None

    def test_engine_sharing_constructor(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path}/shared.db")
        fs_a = DbFileSystem(db_engine=engine)
        fs_b = DbFileSystem(db_engine=engine)
        fs_a.write("ns", "a.md", "x")
        assert fs_b.read("ns", "a.md") == "x"
        assert fs_b.db_engine is engine
        engine.dispose()

    def test_table_autocreation_fresh_schema_postgres(self, pg_engine):
        # Process-unique so parallel test processes cannot collide on create/drop.
        fresh_schema = f"agentfs_fresh_{os.getpid()}"
        fs = DbFileSystem(db_engine=pg_engine, db_schema=fresh_schema)
        try:
            fs.write("ns", "a.md", "x")
            assert fs.read("ns", "a.md") == "x"
        finally:
            with pg_engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {fresh_schema} CASCADE"))

    def test_table_autocreation_sqlite_url(self, tmp_path):
        fs = DbFileSystem(db_url=f"sqlite:///{tmp_path}/fresh.db")
        fs.write("ns", "a.md", "x")
        assert fs.read("ns", "a.md") == "x"

    def test_sqlite_url_creates_missing_parent_dirs(self, tmp_path):
        # sqlite errors on connect if the parent dir is missing; DbFileSystem creates
        # it (matching SqliteDb), so cookbooks need no Path(...).mkdir boilerplate.
        nested = tmp_path / "does" / "not" / "exist" / "x.db"
        fs = DbFileSystem(db_url=f"sqlite:///{nested}")
        fs.write("ns", "a.md", "x")
        assert fs.read("ns", "a.md") == "x"
        assert nested.exists()

    def test_version_starts_at_one_and_increments(self, db_fs):
        assert db_fs.write(NS, "v.md", "a").version == 1
        assert db_fs.write(NS, "v.md", "b").version == 2
        assert db_fs.append(NS, "v.md", "c").version == 3


class TestVersioning:
    def test_expected_version_happy_path(self, db_fs):
        db_fs.write(NS, "v.md", "one")
        meta = db_fs.write(NS, "v.md", "two", expected_version=1)
        assert meta.version == 2
        with pytest.raises(VersionConflictError):
            db_fs.write(NS, "v.md", "three", expected_version=1)


class TestAsyncTwins:
    def test_async_smoke_all_operations(self, db_fs):
        async def flow():
            await db_fs.awrite(NS, "a.md", "hello\n")
            assert await db_fs.aread(NS, "a.md") == "hello\n"
            await db_fs.aappend(NS, "seen/log.md", "one\n")
            assert await db_fs.acontains(NS, ["one"], "seen") == {"one"}
            assert {m.path for m in await db_fs.alist(NS)} == {"a.md", "seen/log.md"}
            assert len(await db_fs.asearch(NS, "hello")) == 1
            await db_fs.amove(NS, "a.md", "b.md")
            usage = await db_fs.ausage(NS)
            assert usage.file_count == 2
            assert await db_fs.adelete(NS, "b.md") is True

        asyncio.run(flow())


class TestAppendCapRace:
    def test_oversized_chunk_refused_even_when_row_exists(self, db_fs):
        """The client-side chunk check must not be conditional on the row existing.

        It used to run only when _stat found no row, so a concurrent delete between
        that check and the upsert sent an oversized chunk down the INSERT arm, which
        the ON CONFLICT WHERE guard does not cover, blowing past the cap (PR review).
        """
        db_fs.append(NS, "log.md", "seed", max_file_bytes=1000)
        with pytest.raises(QuotaExceededError):
            db_fs.append(NS, "log.md", "x" * 2000, max_file_bytes=1000)
        # And the file the delete would have raced is still within the cap.
        assert len(db_fs.read(NS, "log.md").encode("utf-8")) <= 1000

    def test_oversized_chunk_refused_on_missing_row(self, db_fs):
        with pytest.raises(QuotaExceededError):
            db_fs.append(NS, "fresh.md", "x" * 2000, max_file_bytes=1000)
        assert db_fs.read(NS, "fresh.md") is None


class TestAsyncDbRejected:
    def test_async_agno_db_rejected_at_construction(self):
        """An async agno db HAS a db_engine, so a bare hasattr check accepts it and
        the first operation dies inside a sync `with engine.begin()` (PR review).
        Stands in for AsyncPostgresDb without needing the asyncpg driver."""
        from sqlalchemy.ext.asyncio import create_async_engine

        class FakeAsyncDb:
            db_engine = create_async_engine("sqlite+aiosqlite://")

        with pytest.raises(ValueError) as exc:
            DbFileSystem(db=FakeAsyncDb())
        assert "async" in str(exc.value).lower()

    def test_self_move_is_a_noop(self, db_fs):
        db_fs.write(NS, "a.md", "x")
        db_fs.move(NS, "a.md", "a.md")
        assert db_fs.read(NS, "a.md") == "x"
