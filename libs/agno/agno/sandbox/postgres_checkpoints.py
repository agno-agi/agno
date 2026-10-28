"""Checkpoint objects in PostgreSQL, for deployments whose replicas share a database but no filesystem.

Each object is a header row keyed by its sha256 plus its stored bytes in fixed-size chunk
rows. Both are written in one transaction, so an interrupted upload leaves nothing readable.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, Optional, Tuple, Union

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import (
    _CHUNK,
    CheckpointArchive,
    CheckpointObjectNotFound,
    CheckpointRef,
    _drain,
    _regular,
    _thread,
)

try:
    from sqlalchemy import (
        DDL,
        BigInteger,
        Column,
        ForeignKey,
        Integer,
        LargeBinary,
        MetaData,
        String,
        Table,
        event,
        select,
        text,
    )
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.engine import Connection
except ImportError:
    raise ImportError("PostgresCheckpointStore requires sqlalchemy and a PostgreSQL driver")

# Postgres truncates identifiers past 63 bytes, which would let two stores share a chunk table.
_MAX_IDENTIFIER = 63
_CHUNK_SUFFIX = "_chunks"


class PostgresCheckpointStore:
    """Content-addressed immutable checkpoint objects in PostgreSQL tables.

    ``put`` hashes the archive, skips the upload when the object already exists, and
    otherwise writes a header row and the archive in ``chunk_bytes`` rows inside one
    transaction. Concurrent puts of the same bytes serialize on the header row, and the
    later one writes nothing. ``verify`` checks the header's size without reading the
    chunks; ``open_archive`` streams the chunks into a private read-only file, checks its
    size and digest against the reference, and removes it when the context exits, so
    deleting the object meanwhile does not affect a reader that already holds it.

    Tables are created on first use in the database's schema: ``table_name`` for headers
    and ``<table_name>_chunks`` for bytes, which cascades deletes from its header. Pass a
    separate ``PostgresDb`` to keep checkpoint bytes out of the system of record. Every
    captured turn adds one; the sandbox's ``retain_checkpoints`` deletes older ones.

    Async methods support both Postgres adapters. Synchronous methods require
    ``PostgresDb``, as the sandbox coordinator's own store does.

    Args:
        db: The ``PostgresDb`` or ``AsyncPostgresDb`` whose engine and schema hold the tables.
        table_name: Name of the header table; the chunk table appends ``_chunks``.
        max_bytes: The largest object the store accepts, the checkpoint archive limit.
        chunk_bytes: Bytes per chunk row, and the most a read or write holds in memory.
        scratch: Directory for the temporary copy ``open_archive`` yields. The system
            temporary directory otherwise, which may be small on a container.
    """

    def __init__(
        self,
        db: Union[PostgresDb, AsyncPostgresDb],
        *,
        table_name: str = "agno_sandbox_checkpoints",
        max_bytes: int = 1024 * 1024 * 1024,
        chunk_bytes: int = 8 * 1024 * 1024,
        scratch: Optional[Path] = None,
    ) -> None:
        if not isinstance(db, (PostgresDb, AsyncPostgresDb)):
            raise TypeError("PostgresCheckpointStore requires PostgresDb or AsyncPostgresDb")
        if not isinstance(table_name, str) or not table_name:
            raise ValueError("Checkpoint table name must be a nonempty string")
        if len((table_name + _CHUNK_SUFFIX).encode()) > _MAX_IDENTIFIER:
            raise ValueError(
                f"Checkpoint table name must leave room for {_CHUNK_SUFFIX!r} within {_MAX_IDENTIFIER} bytes"
            )
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("Checkpoint object limit must be positive")
        if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= 256 * 1024 * 1024:
            raise ValueError("Checkpoint chunk size must be between 1 byte and 256 MiB")
        self.db = db
        self.max_bytes = max_bytes
        self.chunk_bytes = chunk_bytes
        self.scratch = Path(scratch) if scratch is not None else None
        if self.scratch is not None:
            self.scratch.mkdir(parents=True, exist_ok=True)
        metadata = MetaData(schema=db.db_schema)
        self.objects = Table(
            table_name,
            metadata,
            Column("sha256", String(64), primary_key=True),
            Column("size", BigInteger, nullable=False),
            Column("created_at", BigInteger, nullable=False),
        )
        self.chunks = Table(
            table_name + _CHUNK_SUFFIX,
            metadata,
            Column("sha256", String(64), ForeignKey(self.objects.c.sha256, ondelete="CASCADE"), primary_key=True),
            Column("seq", Integer, primary_key=True),
            Column("data", LargeBinary, nullable=False),
        )
        # Archives are already gzip-compressed; TOAST compression would spend CPU for nothing.
        event.listen(
            self.chunks, "after_create", DDL("ALTER TABLE %(fullname)s ALTER COLUMN data SET STORAGE EXTERNAL")
        )
        self._metadata = metadata
        self._tables_ready = False

    # --------------------------------------------------------------- tables

    def _create(self, connection: Connection) -> None:
        # Concurrent first uses would race CREATE TABLE; one advisory lock per table pair serializes them.
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": self._lock_name})
        # CREATE SCHEMA needs CREATE on the database even when the schema exists, so skip it then.
        if self.db.create_schema and not connection.dialect.has_schema(connection, self.db.db_schema):
            schema = connection.dialect.identifier_preparer.quote_schema(self.db.db_schema)
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        self._metadata.create_all(connection, checkfirst=True)

    @property
    def _lock_name(self) -> str:
        return f"agno.sandbox.checkpoints:{self.db.db_schema}.{self.objects.name}"

    def _ensure_tables(self) -> None:
        if self._tables_ready:
            return
        with self._engine().begin() as connection:
            self._create(connection)
        self._tables_ready = True

    async def _aensure_tables(self) -> None:
        if self._tables_ready:
            return
        if isinstance(self.db, AsyncPostgresDb):
            async with self.db.db_engine.begin() as connection:
                await connection.run_sync(self._create)
            self._tables_ready = True
            return
        await _thread(self._ensure_tables)

    def _engine(self) -> Any:
        if isinstance(self.db, AsyncPostgresDb):
            raise TypeError("Use the async checkpoint store methods with AsyncPostgresDb")
        return self.db.db_engine

    # ------------------------------------------------------------- helpers

    def _digest(self, source: Path) -> CheckpointRef:
        digest, size = hashlib.sha256(), 0
        with _regular(Path(source)) as stream:
            while chunk := stream.read(_CHUNK):
                size += len(chunk)
                if size > self.max_bytes:
                    raise SandboxError("Checkpoint object exceeds its limit")
                digest.update(chunk)
        if size == 0:
            raise SandboxError("Checkpoint object is empty")
        return CheckpointRef(digest.hexdigest(), size)

    @staticmethod
    def _check(reference: CheckpointRef, size: Optional[int]) -> None:
        if size is None:
            raise CheckpointObjectNotFound("Checkpoint object is missing")
        if size != reference.size:
            raise SandboxError("Checkpoint size mismatch")

    def _head_query(self, reference: CheckpointRef) -> Any:
        return select(self.objects.c.size).where(self.objects.c.sha256 == reference.sha256)

    def _chunk_query(self, reference: CheckpointRef, seq: int) -> Any:
        # One row per statement: drivers prefetch server-side cursors in batches, which would not bound memory.
        return select(self.chunks.c.data).where((self.chunks.c.sha256 == reference.sha256) & (self.chunks.c.seq == seq))

    def _claim(self, reference: CheckpointRef) -> Any:
        """Insert the header, or nothing when the object exists. Waits on a concurrent uncommitted put."""
        return (
            insert(self.objects)
            .values(sha256=reference.sha256, size=reference.size, created_at=int(time.time()))
            .on_conflict_do_nothing(index_elements=[self.objects.c.sha256])
            .returning(self.objects.c.sha256)
        )

    def _scratch_file(self) -> Tuple[int, Path]:
        descriptor, name = tempfile.mkstemp(prefix=".checkpoint-", suffix=".tar", dir=self.scratch)
        return descriptor, Path(name)

    @staticmethod
    def _finish_copy(path: Path, reference: CheckpointRef, digest: Any, size: int) -> None:
        if size != reference.size:
            raise SandboxError("Checkpoint size mismatch")
        if digest.hexdigest() != reference.sha256:
            raise SandboxError("Checkpoint checksum mismatch")
        # The copy is the caller's to read, never to edit.
        path.chmod(0o400)

    # ------------------------------------------------------------------ put

    def _write_chunks(self, connection: Connection, source: Path, reference: CheckpointRef) -> None:
        digest, size, seq = hashlib.sha256(), 0, 0
        with _regular(source) as stream:
            while chunk := stream.read(self.chunk_bytes):
                size += len(chunk)
                if size > reference.size:
                    break
                digest.update(chunk)
                connection.execute(self.chunks.insert().values(sha256=reference.sha256, seq=seq, data=chunk))
                seq += 1
        # Raising rolls back the header with the chunks, so a changed source publishes nothing.
        if size != reference.size or digest.hexdigest() != reference.sha256:
            raise SandboxError("Checkpoint source changed while it was stored")

    def put(self, source: Path) -> CheckpointRef:
        engine = self._engine()
        source = Path(source)
        reference = self._digest(source)
        self._ensure_tables()
        with engine.begin() as connection:
            if connection.execute(self._claim(reference)).first() is not None:
                self._write_chunks(connection, source, reference)
        self.verify(reference)
        return reference

    async def aput(self, source: Path) -> CheckpointRef:
        if not isinstance(self.db, AsyncPostgresDb):
            return await _thread(self.put, source)
        source = Path(source)
        reference = await _thread(self._digest, source)
        await self._aensure_tables()
        async with self.db.db_engine.begin() as connection:
            if (await connection.execute(self._claim(reference))).first() is not None:
                digest, size, seq = hashlib.sha256(), 0, 0
                with _regular(source) as stream:
                    while chunk := await _thread(stream.read, self.chunk_bytes):
                        size += len(chunk)
                        if size > reference.size:
                            break
                        digest.update(chunk)
                        await connection.execute(
                            self.chunks.insert().values(sha256=reference.sha256, seq=seq, data=chunk)
                        )
                        seq += 1
                if size != reference.size or digest.hexdigest() != reference.sha256:
                    raise SandboxError("Checkpoint source changed while it was stored")
        await self.averify(reference)
        return reference

    # --------------------------------------------------------------- verify

    def verify(self, reference: CheckpointRef) -> None:
        if reference.size > self.max_bytes:
            raise SandboxError("Checkpoint object exceeds its limit")
        engine = self._engine()
        self._ensure_tables()
        with engine.connect() as connection:
            self._check(reference, connection.execute(self._head_query(reference)).scalar())

    async def averify(self, reference: CheckpointRef) -> None:
        if not isinstance(self.db, AsyncPostgresDb):
            return await _thread(self.verify, reference)
        if reference.size > self.max_bytes:
            raise SandboxError("Checkpoint object exceeds its limit")
        await self._aensure_tables()
        async with self.db.db_engine.connect() as connection:
            self._check(reference, (await connection.execute(self._head_query(reference))).scalar())

    # --------------------------------------------------------- open_archive

    def _download(self, reference: CheckpointRef) -> Path:
        """Copy the object into a private temporary file whose bytes match the reference."""
        engine = self._engine()
        if reference.size > self.max_bytes:
            raise SandboxError("Checkpoint object exceeds its limit")
        self._ensure_tables()
        descriptor, path = self._scratch_file()
        try:
            digest, size = hashlib.sha256(), 0
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                # One snapshot for the header and every chunk: a concurrent delete is either
                # wholly before this read or wholly after it.
                with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                    with connection.begin():
                        self._check(reference, connection.execute(self._head_query(reference)).scalar())
                        seq = 0
                        while (data := connection.execute(self._chunk_query(reference, seq)).scalar()) is not None:
                            size += len(data)
                            if size > reference.size:
                                raise SandboxError("Checkpoint size mismatch")
                            digest.update(data)
                            output.write(data)
                            seq += 1
                output.flush()
                os.fsync(output.fileno())
            self._finish_copy(path, reference, digest, size)
            return path
        except BaseException:
            if descriptor != -1:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise

    async def _adownload(self, reference: CheckpointRef) -> Path:
        assert isinstance(self.db, AsyncPostgresDb)
        if reference.size > self.max_bytes:
            raise SandboxError("Checkpoint object exceeds its limit")
        await self._aensure_tables()
        descriptor, path = self._scratch_file()
        try:
            digest, size = hashlib.sha256(), 0
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                async with self.db.db_engine.connect() as connection:
                    connection = await connection.execution_options(isolation_level="REPEATABLE READ")
                    async with connection.begin():
                        head = await connection.execute(self._head_query(reference))
                        self._check(reference, head.scalar())
                        seq = 0
                        while True:
                            data = (await connection.execute(self._chunk_query(reference, seq))).scalar()
                            if data is None:
                                break
                            size += len(data)
                            if size > reference.size:
                                raise SandboxError("Checkpoint size mismatch")
                            digest.update(data)
                            # _thread drains the write before a cancellation closes the file.
                            await _thread(output.write, data)
                            seq += 1
                await _thread(output.flush)
                await _thread(os.fsync, output.fileno())
            self._finish_copy(path, reference, digest, size)
            return path
        except BaseException:
            if descriptor != -1:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise

    @contextmanager
    def open_archive(self, reference: CheckpointRef) -> Iterator[Path]:
        path = self._download(reference)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    async def _acopy(self, reference: CheckpointRef) -> Path:
        """Download a private copy, removing it when cancellation lands before the caller holds it."""
        if isinstance(self.db, AsyncPostgresDb):
            task = asyncio.ensure_future(self._adownload(reference))
        else:
            task = asyncio.ensure_future(asyncio.to_thread(self._download, reference))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A thread cannot be interrupted, so it finishes and its copy is removed instead.
            if isinstance(self.db, AsyncPostgresDb):
                task.cancel()
            if await _drain(task) is None and not task.cancelled():
                task.result().unlink(missing_ok=True)
            raise

    @asynccontextmanager
    async def aopen_archive(self, reference: CheckpointRef) -> AsyncIterator[Path]:
        path = await self._acopy(reference)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    # --------------------------------------------------------------- delete

    def _delete_query(self, reference: CheckpointRef) -> Any:
        return self.objects.delete().where(self.objects.c.sha256 == reference.sha256)

    def delete(self, reference: CheckpointRef) -> None:
        engine = self._engine()
        self._ensure_tables()
        with engine.begin() as connection:
            connection.execute(self._delete_query(reference))

    async def adelete(self, reference: CheckpointRef) -> None:
        if not isinstance(self.db, AsyncPostgresDb):
            return await _thread(self.delete, reference)
        await self._aensure_tables()
        async with self.db.db_engine.begin() as connection:
            await connection.execute(self._delete_query(reference))

    # -------------------------------------------------------------- restore

    def restore(
        self, reference: CheckpointRef, destination: Path, *, archive: Optional[CheckpointArchive] = None
    ) -> Dict[str, Any]:
        with self.open_archive(reference) as source:
            return (archive or CheckpointArchive()).restore(source, destination)

    async def arestore(
        self, reference: CheckpointRef, destination: Path, *, archive: Optional[CheckpointArchive] = None
    ) -> Dict[str, Any]:
        async with self.aopen_archive(reference) as source:
            return await (archive or CheckpointArchive()).arestore(source, destination)
