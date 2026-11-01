"""PostgresCheckpointStore against a real PostgreSQL, through both Postgres adapters."""

import asyncio
import hashlib
import os
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Table, create_engine, event, text

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.sandbox import SandboxError
from agno.sandbox.checkpoint import (
    CheckpointArchive,
    CheckpointLimits,
    CheckpointObjectNotFound,
    CheckpointRef,
    CheckpointStore,
)
from agno.sandbox.postgres_checkpoints import PostgresCheckpointStore

URL = os.environ.get("AGNO_TEST_SANDBOX_DB_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="Set AGNO_TEST_SANDBOX_DB_URL")]
STATE = {"run_id": "r", "native_id": "n", "conversation": ["hello"]}


@pytest.fixture
def roots(tmp_path):
    paths = {name: tmp_path / name for name in ("workspace", "native")}
    for path in paths.values():
        path.mkdir()
    (paths["workspace"] / "app.py").write_text("print('hello')")
    # Random bytes do not compress, so the archive spans several small chunks.
    (paths["workspace"] / "data.bin").write_bytes(os.urandom(64 * 1024))
    (paths["native"] / "transcript.jsonl").write_text('{"message":"remember this"}\n')
    return paths


def capture(directory, roots, *, limits=CheckpointLimits()):
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "checkpoint.tar"
    CheckpointArchive(limits).capture(roots, archive, state=STATE)
    return archive


@pytest.fixture
def sql():
    engine = create_engine(URL)
    yield engine
    engine.dispose()


@pytest_asyncio.fixture(params=[PostgresDb, AsyncPostgresDb], ids=["sync_db", "async_db"])
async def make(request, sql):
    """Build stores on fresh tables; every store from one test shares those tables."""
    name = "ckpt_" + uuid4().hex[:12]
    dbs = []

    def build(**kwargs):
        db = request.param(db_url=URL)
        dbs.append(db)
        return PostgresCheckpointStore(db, table_name=name, chunk_bytes=kwargs.pop("chunk_bytes", 16 * 1024), **kwargs)

    build.table = name
    yield build
    for db in dbs:
        if isinstance(db, AsyncPostgresDb):
            await db.db_engine.dispose()
        else:
            db.db_engine.dispose()
    with sql.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS ai.{name}_chunks, ai.{name}"))


def rows(sql, table, reference=None):
    where = f" WHERE sha256 = '{reference.sha256}'" if reference else ""
    with sql.connect() as connection:
        objects = connection.execute(text(f"SELECT count(*) FROM ai.{table}{where}")).scalar()
        chunks = connection.execute(text(f"SELECT count(*) FROM ai.{table}_chunks{where}")).scalar()
    return objects, chunks


async def test_the_store_satisfies_the_contract_and_round_trips_a_checkpoint(make, sql, tmp_path, roots):
    store = make()
    assert isinstance(store, CheckpointStore)
    source = capture(tmp_path / "src", roots)
    reference = await store.aput(source)
    assert reference.size == source.stat().st_size
    assert reference.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    expected_chunks = -(-reference.size // store.chunk_bytes)
    assert expected_chunks > 1, "the fixture must exercise more than one chunk"
    assert rows(sql, make.table, reference) == (1, expected_chunks)
    assert await store.averify(reference) is None
    async with store.aopen_archive(reference) as path:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
        state = await CheckpointArchive().arestore(path, tmp_path / "restored")
    assert not path.exists(), "the materialized copy is removed when the caller is done"
    assert state == STATE
    assert (tmp_path / "restored" / "workspace" / "app.py").read_text() == "print('hello')"
    assert rows(sql, make.table, reference) == (1, expected_chunks), "reading never removes the object"


async def test_another_replica_restores_what_one_captured(make, tmp_path, roots):
    reference = await make().aput(capture(tmp_path / "src", roots))
    state = await make().arestore(reference, tmp_path / "elsewhere")
    assert state == STATE
    assert (tmp_path / "elsewhere" / "native" / "transcript.jsonl").exists()


async def test_put_of_an_existing_object_writes_nothing(make, sql, tmp_path, roots, monkeypatch):
    store = make()
    source = capture(tmp_path / "src", roots)
    reference = await store.aput(source)
    with sql.connect() as connection:
        created = connection.execute(text(f"SELECT created_at FROM ai.{make.table}")).scalar()

    def refuse(*args, **kwargs):
        raise AssertionError("an existing object must not be written again")

    # Chunk rows are the only writes through Table.insert; the header uses the dialect's upsert.
    monkeypatch.setattr(Table, "insert", refuse)
    assert await make().aput(source) == reference
    assert await store.aput(source) == reference
    with sql.connect() as connection:
        assert connection.execute(text(f"SELECT created_at FROM ai.{make.table}")).scalar() == created


async def test_concurrent_puts_of_the_same_bytes_store_one_object(make, sql, tmp_path, roots):
    source = capture(tmp_path / "src", roots)
    references = await asyncio.gather(*(make().aput(source) for _ in range(4)))
    assert len(set(references)) == 1
    assert rows(sql, make.table, references[0]) == (1, -(-references[0].size // 16384))


async def test_a_put_whose_source_changes_publishes_nothing(make, sql, tmp_path, roots):
    store = make()
    source = capture(tmp_path / "src", roots)
    digest = store._digest

    def then_change(path):
        reference = digest(path)
        with open(path, "r+b") as stream:
            stream.seek(reference.size - 1)
            stream.write(b"\x00" if stream.read(1) != b"\x00" else b"\x01")
        return reference

    store._digest = then_change
    with pytest.raises(SandboxError, match="changed while it was stored"):
        await store.aput(source)
    assert rows(sql, make.table) == (0, 0), "the header rolls back with every chunk already written"


async def test_verify_and_open_fail_on_a_tampered_or_truncated_object(make, sql, tmp_path, roots):
    store = make()
    reference = await store.aput(capture(tmp_path / "src", roots))
    with sql.begin() as connection:
        connection.execute(
            text(f"UPDATE ai.{make.table}_chunks SET data = set_byte(data, 0, 255 - get_byte(data, 0)) WHERE seq = 1")
        )
    assert await store.averify(reference) is None, "verify answers from the header, as the contract allows"
    with pytest.raises(SandboxError, match="checksum mismatch"):
        async with store.aopen_archive(reference):
            pass
    with sql.begin() as connection:
        connection.execute(
            text(f"DELETE FROM ai.{make.table}_chunks WHERE seq = (SELECT max(seq) FROM ai.{make.table}_chunks)")
        )
    with pytest.raises(SandboxError, match="size mismatch"):
        async with store.aopen_archive(reference):
            pass
    with sql.begin() as connection:
        connection.execute(text(f"UPDATE ai.{make.table} SET size = size + 1"))
    with pytest.raises(SandboxError, match="size mismatch"):
        await store.averify(reference)
    assert list(tmp_path.glob("**/.checkpoint-*")) == []


async def test_a_missing_object_is_reported_through_every_access(make, tmp_path, roots):
    store = make()
    reference = await store.aput(capture(tmp_path / "src", roots))
    await store.adelete(reference)
    await store.adelete(reference)
    with pytest.raises(CheckpointObjectNotFound):
        await store.averify(reference)
    with pytest.raises(CheckpointObjectNotFound):
        async with store.aopen_archive(reference):
            pass
    with pytest.raises(CheckpointObjectNotFound):
        await store.arestore(reference, tmp_path / "restored")
    unknown = CheckpointRef("f" * 64, 10)
    with pytest.raises(CheckpointObjectNotFound):
        await make().averify(unknown)


async def test_deleting_an_open_object_leaves_the_reader_its_copy(make, sql, tmp_path, roots):
    store = make(scratch=tmp_path / "scratch")
    reference = await store.aput(capture(tmp_path / "src", roots))
    async with store.aopen_archive(reference) as path:
        assert path.parent == tmp_path / "scratch"
        assert path.stat().st_mode & 0o777 == 0o400, "the caller reads the copy, never edits it"
        await store.adelete(reference)
        assert rows(sql, make.table) == (0, 0), "the chunks cascade with their header"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    assert list((tmp_path / "scratch").iterdir()) == []


async def test_the_object_limit_applies_before_any_write(make, sql, tmp_path, roots):
    store = make(max_bytes=1024)
    with pytest.raises(SandboxError, match="exceeds its limit"):
        await store.aput(capture(tmp_path / "src", roots))
    with pytest.raises(SandboxError, match="exceeds its limit"):
        await store.averify(CheckpointRef("a" * 64, 2048))
    assert not store._tables_ready, "an oversized put fails before touching the database"


async def test_chunk_bytes_are_stored_without_recompression(make, sql, tmp_path, roots):
    store = make()
    await store.aput(capture(tmp_path / "src", roots))
    with sql.connect() as connection:
        storage = connection.execute(
            text("SELECT attstorage FROM pg_attribute WHERE attrelid = :table ::regclass AND attname = 'data'"),
            {"table": f"ai.{make.table}_chunks"},
        ).scalar()
    assert storage == "e"


async def test_sync_access_matches_async_access(make, tmp_path, roots):
    store = make()
    if isinstance(store.db, AsyncPostgresDb):
        source = capture(tmp_path / "src", roots)
        for call in (
            lambda: store.put(source),
            lambda: store.verify(CheckpointRef("a" * 64, 10)),
            lambda: store.delete(CheckpointRef("a" * 64, 10)),
        ):
            with pytest.raises(TypeError, match="async checkpoint store methods"):
                call()
        with pytest.raises(TypeError, match="async checkpoint store methods"):
            with store.open_archive(CheckpointRef("a" * 64, 10)):
                pass
        return
    reference = store.put(capture(tmp_path / "src", roots))
    assert reference == await store.aput(tmp_path / "src" / "checkpoint.tar")
    store.verify(reference)
    with store.open_archive(reference) as path:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    assert store.restore(reference, tmp_path / "restored") == STATE
    store.delete(reference)
    with pytest.raises(CheckpointObjectNotFound):
        store.verify(reference)


async def test_configuration_is_validated():
    db = PostgresDb(db_url=URL)
    try:
        with pytest.raises(TypeError):
            PostgresCheckpointStore(object())  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="nonempty"):
            PostgresCheckpointStore(db, table_name="")
        with pytest.raises(ValueError, match="63 bytes"):
            PostgresCheckpointStore(db, table_name="t" * 57)
        PostgresCheckpointStore(db, table_name="t" * 56)
        with pytest.raises(ValueError, match="limit must be positive"):
            PostgresCheckpointStore(db, max_bytes=0)
        for size in (0, 256 * 1024 * 1024 + 1):
            with pytest.raises(ValueError, match="chunk size"):
                PostgresCheckpointStore(db, chunk_bytes=size)
    finally:
        db.db_engine.dispose()


async def test_a_reader_fetches_one_chunk_per_query(make, tmp_path, roots):
    # Drivers prefetch server-side cursors in batches (asyncpg: 50 rows), so a streamed read is not chunk-bounded.
    store = make()
    reference = await store.aput(capture(tmp_path / "src", roots))
    chunks = -(-reference.size // store.chunk_bytes)
    engine = store.db.db_engine
    engine = getattr(engine, "sync_engine", engine)
    reads = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if f"FROM ai.{make.table}_chunks" in statement:
            reads.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        async with store.aopen_archive(reference) as path:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(reads) >= chunks > 1


async def test_cancelling_an_open_leaves_no_copy_behind(make, tmp_path, roots, monkeypatch):
    store = make(scratch=tmp_path / "scratch")
    reference = await store.aput(capture(tmp_path / "src", roots))
    if isinstance(store.db, AsyncPostgresDb):
        # The async download is interruptible: cancel it while it writes chunks.
        import agno.sandbox.postgres_checkpoints as module

        thread = module._thread

        async def slow(function, *args, **kwargs):
            await asyncio.sleep(0.1)
            return await thread(function, *args, **kwargs)

        monkeypatch.setattr(module, "_thread", slow)
    else:
        # A thread cannot be interrupted: cancel after its copy exists, before the caller holds it.
        download = store._download

        def slow(ref):
            path = download(ref)
            time.sleep(0.5)
            return path

        store._download = slow

    async def open_and_hold():
        async with store.aopen_archive(reference):
            await asyncio.sleep(10)

    task = asyncio.create_task(open_and_hold())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert list((tmp_path / "scratch").iterdir()) == []
