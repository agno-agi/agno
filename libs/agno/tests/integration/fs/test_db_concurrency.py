"""Concurrency and atomicity tests for DbFileSystem (spec D9/D13), both dialects."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from agno.fs.errors import QuotaExceededError, VersionConflictError

NS = "conc"


class TestConcurrentAppends:
    def test_32_concurrent_appends_all_land_intact(self, db_fs):
        lines = [f"record-{i:02d}" for i in range(32)]

        def append_one(line: str):
            return db_fs.append(NS, "seen/log.md", line)

        with ThreadPoolExecutor(max_workers=32) as pool:
            metas = list(pool.map(append_one, lines))

        content = db_fs.read(NS, "seen/log.md")
        stored = content.split("\n")
        assert stored[-1] == ""  # trailing newline
        assert sorted(stored[:-1]) == sorted(lines)  # every line intact, in some order
        assert "" not in stored[:-1]  # no spurious blank lines
        final = db_fs._stat(NS, "seen/log.md")
        assert final.version == 32
        assert final.size_bytes == sum(len((line + "\n").encode("utf-8")) for line in lines)
        assert max(m.version for m in metas) == 32

    def test_cap_under_contention_never_exceeded(self, db_fs):
        max_file_bytes = 100
        lines = [f"row-{i:02d}xxx" for i in range(32)]  # 9 bytes + newline = 10 each

        def append_one(line: str):
            try:
                db_fs.append(NS, "cap.md", line, max_file_bytes=max_file_bytes)
                return "ok"
            except QuotaExceededError as e:
                assert e.scope == "file"
                assert e.limit == max_file_bytes
                return "blocked"

        with ThreadPoolExecutor(max_workers=16) as pool:
            outcomes = list(pool.map(append_one, lines))

        content = db_fs.read(NS, "cap.md")
        size = len(content.encode("utf-8"))
        assert size <= max_file_bytes
        assert outcomes.count("ok") == size // 10
        assert outcomes.count("blocked") == 32 - outcomes.count("ok")
        for line in content.split("\n")[:-1]:
            assert line in lines  # no partial writes


class TestGuardDetection:
    def test_blocked_append_raises_via_returning(self, db_fs):
        """The guard must be detected via RETURNING, never result.rowcount: on
        psycopg3 rowcount is -1 for the guarded upsert whether it blocked or not,
        so a rowcount implementation never raises here on Postgres (spec D9)."""
        db_fs.append(NS, "guard.md", "0123456789", max_file_bytes=100)  # 11 bytes stored
        with pytest.raises(QuotaExceededError) as excinfo:
            db_fs.append(NS, "guard.md", "x" * 95, max_file_bytes=100)
        assert excinfo.value.scope == "file"
        assert excinfo.value.current == 11 + 96  # existing + chunk (no separator needed)
        assert excinfo.value.limit == 100
        assert db_fs.read(NS, "guard.md") == "0123456789\n"


class TestCas:
    def test_two_writers_same_expected_version(self, db_fs):
        db_fs.write(NS, "cas.md", "base")  # version 1

        results = []

        def cas_write(marker: str):
            try:
                db_fs.write(NS, "cas.md", marker, expected_version=1)
                results.append(("ok", marker))
            except VersionConflictError as e:
                results.append(("conflict", e))

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(cas_write, ["writer-a", "writer-b"]))

        outcomes = sorted(kind for kind, _ in results)
        assert outcomes == ["conflict", "ok"]
        conflict = next(payload for kind, payload in results if kind == "conflict")
        assert conflict.expected == 1
        assert conflict.actual == 2
        winner = next(payload for kind, payload in results if kind == "ok")
        assert db_fs.read(NS, "cas.md") == winner

    def test_cas_on_missing_file(self, db_fs):
        with pytest.raises(VersionConflictError) as excinfo:
            db_fs.write(NS, "ghost.md", "x", expected_version=3)
        assert excinfo.value.expected == 3
        assert excinfo.value.actual is None


class TestColdStartAndCyclicMoves:
    def test_concurrent_first_use_across_instances(self, db_fs):
        """A dozen instances sharing one engine race CREATE SCHEMA/TABLE on
        genuinely-cold first use (the table does not exist yet) — losing the
        DDL race must be silent, not an IntegrityError burst on cold start."""
        from sqlalchemy import text as sql_text

        from agno.fs.db import DbFileSystem

        engine = db_fs.db_engine
        cold_table = "agno_fs_cold_start"
        schema_prefix = f"{db_fs.db_schema}." if db_fs.db_schema else ""
        with engine.begin() as conn:
            conn.execute(sql_text(f"DROP TABLE IF EXISTS {schema_prefix}{cold_table}"))
        instances = [
            DbFileSystem(db_engine=engine, table_name=cold_table, db_schema=db_fs.db_schema)
            if db_fs.dialect == "postgresql"
            else DbFileSystem(db_engine=engine, table_name=cold_table)
            for _ in range(12)
        ]

        def first_use(pair):
            index, instance = pair
            instance.write(NS, f"cold/{index}.md", "x")

        try:
            with ThreadPoolExecutor(max_workers=12) as pool:
                list(pool.map(first_use, enumerate(instances)))
            assert len(instances[0].list(NS, "cold")) == 12
        finally:
            with engine.begin() as conn:
                conn.execute(sql_text(f"DROP TABLE IF EXISTS {schema_prefix}{cold_table}"))

    def test_cyclic_concurrent_overwrite_moves_do_not_deadlock(self, db_fs):
        """a->b and b->a with overwrite=True concurrently: without deterministic
        lock ordering the two row locks are acquired in opposite order and
        Postgres aborts one mover with an uncaught DeadlockDetected."""
        for round_index in range(10):
            db_fs.write(NS, "cyc-a.md", f"content-a-{round_index}")
            db_fs.write(NS, "cyc-b.md", f"content-b-{round_index}")

            def mover(direction):
                src, dst = direction
                try:
                    db_fs.move(NS, src, dst, overwrite=True)
                    return "ok"
                except FileNotFoundError:
                    return "missing"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(mover, [("cyc-a.md", "cyc-b.md"), ("cyc-b.md", "cyc-a.md")]))
            assert set(outcomes) <= {"ok", "missing"}
            remaining = {m.path for m in db_fs.list(NS)} & {"cyc-a.md", "cyc-b.md"}
            for path in remaining:
                db_fs.delete(NS, path)


class TestLastWriterWins:
    def test_concurrent_plain_writes_leave_one_intact_content(self, db_fs):
        """A read-then-INSERT-or-UPDATE implementation passes every serial test
        and fails this one (spec D13): N writers to one missing path must all
        succeed atomically and leave exactly one intact content."""
        contents = [f"content-from-writer-{i:02d}" for i in range(16)]

        def write_one(body: str):
            db_fs.write(NS, "lww.md", body)  # raises on a non-atomic implementation

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(write_one, contents))

        final = db_fs.read(NS, "lww.md")
        assert final in contents
        meta = db_fs._stat(NS, "lww.md")
        assert meta.version == 16
        assert meta.size_bytes == len(final.encode("utf-8"))
