"""A metrics refresh on SQLite, MySQL, SingleStore and MongoDB must scale with sessions, not legacy runs.

The same refresh fixed for PostgreSQL, pinned on every other adapter that has a runs table:

- Runs are matched to the refresh's sessions without one bind value per session, which overflows
  SQLite's variable limit and MongoDB's 16 MB query document.
- The legacy sessions `runs` column, kept by the v3.0.0 migration until cleanup_legacy_runs_column()
  is called, is never loaded into the process: only each run's model and provider are read.
- Runs are still counted once whether they live in the runs table, only in the legacy column, or in both.
- A failed read surfaces as an error instead of an empty refresh.

Runs against live servers (MySQL on 3306, SingleStore on 3307, MongoDB on 27017) with a unique
schema or database per test; a backend whose server is absent is skipped.
"""

import asyncio
import inspect
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import pytest
from sqlalchemy import MetaData, Table, create_engine, inspect as sa_inspect, text

from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.db.mysql import AsyncMySQLDb, MySQLDb
from agno.db.singlestore import SingleStoreDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb

MYSQL_URL = "mysql+pymysql://root:ai@localhost:3306"
ASYNC_MYSQL_URL = "mysql+asyncmy://root:ai@localhost:3306"
SINGLESTORE_URL = "mysql+pymysql://root:admin@localhost:3307"
MONGO_URL = "mongodb://mongoadmin:secret@localhost:27017"

SESSIONS_TABLE = "agno_sessions"
RUNS_TABLE = "agno_runs"
RUNS_PER_SESSION = 20
SMALL_SESSIONS = 10
# ~150 MB of legacy runs JSON: far above what a refresh needs, well within a CI runner's memory.
LARGE_SESSIONS = 750
RUN_BYTES = 10_000
# Loading the legacy column costs the whole payload (>1x); reading model and provider costs a fraction.
MAX_GROWTH_FRACTION = 0.5
# Session ids long enough that this many overflow MongoDB's 16 MB query document in one $in.
MONGO_SESSIONS_PAST_DOCUMENT_LIMIT = 17_000
MONGO_LONG_SESSION_ID_BYTES = 1_000


def _created_at() -> int:
    return int(time.time()) - 86400


class Backend:
    """How to build, seed and drop one adapter's store for a test namespace."""

    def __init__(
        self,
        name: str,
        target: Callable[[str], Any],
        seeder: Callable[[str], Any],
        reachable: Callable[[], bool],
        drop: Callable[[str], None],
        is_mongo: bool = False,
    ):
        self.name = name
        self.target = target
        self.seeder = seeder
        self.reachable = reachable
        self.drop = drop
        self.is_mongo = is_mongo


def _sql_reachable(url: str) -> Callable[[], bool]:
    def probe() -> bool:
        # A raw probe, not an adapter call: adapter methods catch and log connection errors.
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            engine.dispose()

    return probe


def _drop_sql_schema(url: str) -> Callable[[str], None]:
    def drop(ns: str) -> None:
        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS `{ns}`"))
        finally:
            engine.dispose()

    return drop


def _sqlite_file(ns: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"{ns}.db")


def _drop_sqlite(ns: str) -> None:
    if os.path.exists(_sqlite_file(ns)):
        os.remove(_sqlite_file(ns))


def _mongo_reachable() -> bool:
    from pymongo import MongoClient

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
        return True
    except Exception:
        return False
    finally:
        client.close()


def _drop_mongo(ns: str) -> None:
    from pymongo import MongoClient

    client = MongoClient(MONGO_URL)
    try:
        client.drop_database(ns)
    finally:
        client.close()


BACKENDS: Dict[str, Backend] = {
    b.name: b
    for b in [
        Backend(
            "sqlite",
            lambda ns: SqliteDb(db_file=_sqlite_file(ns)),
            lambda ns: SqliteDb(db_file=_sqlite_file(ns)),
            lambda: True,
            _drop_sqlite,
        ),
        Backend(
            "async_sqlite",
            lambda ns: AsyncSqliteDb(db_file=_sqlite_file(ns)),
            lambda ns: SqliteDb(db_file=_sqlite_file(ns)),
            lambda: True,
            _drop_sqlite,
        ),
        Backend(
            "mysql",
            lambda ns: MySQLDb(db_url=MYSQL_URL, db_schema=ns),
            lambda ns: MySQLDb(db_url=MYSQL_URL, db_schema=ns),
            _sql_reachable(MYSQL_URL),
            _drop_sql_schema(MYSQL_URL),
        ),
        Backend(
            "async_mysql",
            lambda ns: AsyncMySQLDb(db_url=ASYNC_MYSQL_URL, db_schema=ns),
            lambda ns: MySQLDb(db_url=MYSQL_URL, db_schema=ns),
            _sql_reachable(MYSQL_URL),
            _drop_sql_schema(MYSQL_URL),
        ),
        Backend(
            "singlestore",
            lambda ns: SingleStoreDb(db_url=SINGLESTORE_URL, db_schema=ns),
            lambda ns: SingleStoreDb(db_url=SINGLESTORE_URL, db_schema=ns),
            _sql_reachable(SINGLESTORE_URL),
            _drop_sql_schema(SINGLESTORE_URL),
        ),
        Backend(
            "mongo",
            lambda ns: MongoDb(db_url=MONGO_URL, db_name=ns),
            lambda ns: MongoDb(db_url=MONGO_URL, db_name=ns),
            _mongo_reachable,
            _drop_mongo,
            is_mongo=True,
        ),
        Backend(
            "async_mongo",
            lambda ns: AsyncMongoDb(db_url=MONGO_URL, db_name=ns),
            lambda ns: MongoDb(db_url=MONGO_URL, db_name=ns),
            _mongo_reachable,
            _drop_mongo,
            is_mongo=True,
        ),
    ]
}
SQL_BACKENDS = [name for name, b in BACKENDS.items() if not b.is_mongo]
MONGO_BACKENDS = [name for name, b in BACKENDS.items() if b.is_mongo]


@pytest.fixture
def ns(request):
    backend = BACKENDS[request.node.callspec.params["backend"]]
    if not backend.reachable():
        pytest.skip(f"{backend.name} server not reachable")
    name = f"metrics_{uuid.uuid4().hex[:8]}"
    yield name
    backend.drop(name)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _legacy_run(session_id: str, index: int, run_bytes: int, provider: bool = True) -> Dict[str, Any]:
    run = {
        "run_id": f"{session_id}_r{index}",
        "agent_id": "a1",
        "status": "COMPLETED",
        "created_at": _created_at() + index,
        "model": "gpt-5.5",
        "content": uuid.uuid4().hex * max(run_bytes // 32, 1),
    }
    if provider:
        run["model_provider"] = "OpenAI"
    return run


def seed(
    backend: Backend,
    ns: str,
    legacy_sessions: int = 0,
    first: int = 1,
    run_bytes: int = 1_000,
    migrated: bool = False,
    provider: bool = True,
    table_run_sessions: int = 0,
    session_id_bytes: int = 0,
) -> int:
    """Add sessions created yesterday and return the bytes of legacy runs JSON added.

    ``legacy_sessions`` hold their runs in the legacy column, also copied to the runs table
    when ``migrated``. ``table_run_sessions`` hold one run in the runs table and no legacy runs.
    """
    import json

    db = backend.seeder(ns)
    sessions: List[Dict[str, Any]] = []
    runs: List[Dict[str, Any]] = []
    payload = 0
    for s in range(first, first + legacy_sessions):
        session_id = f"s{s}"
        legacy = [_legacy_run(session_id, r, run_bytes, provider) for r in range(RUNS_PER_SESSION)]
        payload += len(json.dumps(legacy))
        sessions.append({"session_id": session_id, "runs": legacy})
        if migrated:
            runs.extend(
                {"run_id": run["run_id"], "session_id": session_id, "model": "gpt-5.5", "provider": "OpenAI"}
                for run in legacy
            )
    for s in range(table_run_sessions):
        session_id = f"t{s}".ljust(session_id_bytes, "x")
        sessions.append({"session_id": session_id, "runs": None})
        runs.append({"run_id": f"t{s}_r0", "session_id": session_id, "model": "gpt-5.5", "provider": "OpenAI"})

    if backend.is_mongo:
        sessions_collection = db._get_collection("sessions", create_collection_if_not_found=True)
        runs_collection = db._get_collection("runs", create_collection_if_not_found=True)
        documents = []
        for s in sessions:
            document = {"session_id": s["session_id"], "session_type": "agent", "user_id": "u1"}
            document["created_at"] = _created_at()
            if s["runs"] is not None:
                document["runs"] = s["runs"]
            documents.append(document)
        sessions_collection.insert_many(documents)
        if runs:
            runs_collection.insert_many(
                [
                    {
                        "run_id": r["run_id"],
                        "session_id": r["session_id"],
                        "run_data": {"model": r["model"], "model_provider": r["provider"]},
                    }
                    for r in runs
                ]
            )
        return payload

    db._get_table("sessions", create_table_if_not_found=True)
    db._get_table("runs", create_table_if_not_found=True)
    engine = db.db_engine
    schema = getattr(db, "db_schema", None)
    qualified = f"`{schema}`.`{SESSIONS_TABLE}`" if schema else SESSIONS_TABLE
    columns = {c["name"] for c in sa_inspect(engine).get_columns(SESSIONS_TABLE, schema=schema)}
    if legacy_sessions and "runs" not in columns:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {qualified} ADD COLUMN runs JSON"))

    session_rows = []
    for s in sessions:
        row = {"session_id": s["session_id"], "session_type": "agent", "user_id": "u1", "created_at": _created_at()}
        if s["runs"] is not None:
            row["runs"] = s["runs"]
        session_rows.append(row)
    sessions_name = f"{schema}.{SESSIONS_TABLE}" if schema else SESSIONS_TABLE
    runs_name = f"{schema}.{RUNS_TABLE}" if schema else RUNS_TABLE
    _sql_insert_qualified(engine, sessions_name, session_rows)
    _sql_insert_qualified(
        engine,
        runs_name,
        [
            {
                "run_id": r["run_id"],
                "session_id": r["session_id"],
                "run_type": "agent",
                "run_data": {"model": r["model"], "model_provider": r["provider"]},
                "created_at": _created_at(),
            }
            for r in runs
        ],
        chunk=5_000,
    )
    return payload


def _sql_insert_qualified(engine, name: str, rows: List[Dict[str, Any]], chunk: int = 50) -> None:
    if not rows:
        return
    schema, _, table_name = name.rpartition(".")
    table = Table(table_name, MetaData(), schema=schema or None, autoload_with=engine)
    with engine.begin() as conn:
        for start in range(0, len(rows), chunk):
            conn.execute(table.insert(), rows[start : start + chunk])


def add_v3_session(backend: Backend, ns: str) -> None:
    """A session written after the upgrade: no legacy runs."""
    from agno.session.agent import AgentSession

    backend.seeder(ns).upsert_session(
        AgentSession(session_id="v3_session", agent_id="a1", user_id="u1", created_at=_created_at())
    )


def calculate(backend: Backend, ns: str, patch: Optional[Callable[[Any], None]] = None) -> Optional[List[dict]]:
    db = backend.target(ns)
    if patch is not None:
        patch(db)
    if not inspect.iscoroutinefunction(db.calculate_metrics):
        return db.calculate_metrics()

    async def _run():
        try:
            return await db.calculate_metrics()
        finally:
            engine = getattr(db, "db_engine", None)
            if engine is not None and hasattr(engine, "dispose"):
                await engine.dispose()

    return asyncio.run(_run())


def _model_metrics(result: List[dict]) -> List[dict]:
    return sorted(result[0]["model_metrics"], key=lambda m: (m["model_id"], m["model_provider"]))


# ---------------------------------------------------------------------------
# Every run is counted once, wherever it is stored
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_count_migrated_unmigrated_and_v3_runs_once(ns, backend):
    """Migrated sessions count from the runs table, unmigrated ones from the legacy column, v3 ones have none."""
    b = BACKENDS[backend]
    seed(b, ns, legacy_sessions=SMALL_SESSIONS, migrated=True)
    seed(b, ns, legacy_sessions=SMALL_SESSIONS, first=SMALL_SESSIONS + 1)
    # A legacy run without a provider is reported under an empty provider
    seed(b, ns, legacy_sessions=1, first=2 * SMALL_SESSIONS + 1, provider=False)
    add_v3_session(b, ns)

    result = calculate(b, ns)

    assert result is not None and len(result) == 1
    tracked_runs = 2 * SMALL_SESSIONS * RUNS_PER_SESSION
    assert result[0]["agent_sessions_count"] == 2 * SMALL_SESSIONS + 2
    assert result[0]["agent_runs_count"] == tracked_runs + RUNS_PER_SESSION
    assert _model_metrics(result) == [
        {"model_id": "gpt-5.5", "model_provider": "", "count": RUNS_PER_SESSION},
        {"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": tracked_runs},
    ]


# ---------------------------------------------------------------------------
# Runs are matched without one bind value per session
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["sqlite", "async_sqlite"])
def test_sqlite_metrics_past_variable_limit(ns, backend):
    """More sessions than SQLite accepts bound variables in one statement are all counted."""
    b = BACKENDS[backend]
    limit = sqlite3.connect(":memory:").getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    seed(b, ns, table_run_sessions=limit + 1)

    result = calculate(b, ns)

    assert result is not None and len(result) == 1
    assert result[0]["agent_sessions_count"] == limit + 1
    assert result[0]["agent_runs_count"] == limit + 1


@pytest.mark.parametrize("backend", MONGO_BACKENDS)
def test_mongo_metrics_past_query_document_limit(ns, backend):
    """More session ids than fit one 16 MB query document are all counted."""
    b = BACKENDS[backend]
    seed(
        b,
        ns,
        table_run_sessions=MONGO_SESSIONS_PAST_DOCUMENT_LIMIT,
        session_id_bytes=MONGO_LONG_SESSION_ID_BYTES,
    )

    result = calculate(b, ns)

    assert result is not None and len(result) == 1
    assert result[0]["agent_sessions_count"] == MONGO_SESSIONS_PAST_DOCUMENT_LIMIT
    assert result[0]["agent_runs_count"] == MONGO_SESSIONS_PAST_DOCUMENT_LIMIT


# ---------------------------------------------------------------------------
# A failed read surfaces as an error
# ---------------------------------------------------------------------------


def _rename_column(backend: Backend, ns: str, table: str, column: str) -> None:
    """Break a table the way a schema mismatch would, so reading it raises."""
    db = backend.seeder(ns)
    schema = getattr(db, "db_schema", None)
    with db.db_engine.begin() as conn:
        conn.execute(
            text(f"ALTER TABLE {f'`{schema}`.' if schema else ''}{table} RENAME COLUMN {column} TO {column}_old")
        )


def _pin_starting_date(db) -> None:
    """Start the refresh yesterday without reading the sessions, so the sessions read is what fails."""
    from datetime import datetime, timedelta, timezone

    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)

    async def astarting(*args, **kwargs):
        return yesterday

    if inspect.iscoroutinefunction(db._get_metrics_calculation_starting_date):
        db._get_metrics_calculation_starting_date = astarting
    else:
        db._get_metrics_calculation_starting_date = lambda *args, **kwargs: yesterday


@pytest.mark.parametrize("backend", SQL_BACKENDS)
def test_sql_metrics_raise_when_runs_cannot_be_read(ns, backend):
    b = BACKENDS[backend]
    seed(b, ns, table_run_sessions=1)
    _rename_column(b, ns, RUNS_TABLE, "run_data")

    with pytest.raises(Exception, match="invalid schema"):
        calculate(b, ns, patch=_pin_starting_date)


@pytest.mark.parametrize("backend", SQL_BACKENDS)
def test_sql_metrics_raise_when_first_session_date_cannot_be_read(ns, backend):
    b = BACKENDS[backend]
    seed(b, ns, table_run_sessions=1)
    _rename_column(b, ns, SESSIONS_TABLE, "created_at")

    with pytest.raises(Exception, match="invalid schema"):
        calculate(b, ns)


@pytest.mark.parametrize("backend", MONGO_BACKENDS)
def test_mongo_metrics_raise_when_runs_cannot_be_read(ns, backend):
    b = BACKENDS[backend]
    seed(b, ns, table_run_sessions=1)

    def patch(db):
        _pin_starting_date(db)
        base = type(db)

        # A subclass, not an instance attribute: AsyncMongoDb drops instance attributes named *_collection
        # whenever it binds to a new event loop
        if inspect.iscoroutinefunction(base._get_collection):

            class Failing(base):  # type: ignore[valid-type,misc]
                async def _get_collection(self, table_type, *args, **kwargs):
                    if table_type == "runs":
                        raise RuntimeError("runs collection unavailable")
                    return await super()._get_collection(table_type, *args, **kwargs)

        else:

            class Failing(base):  # type: ignore[valid-type,misc,no-redef]
                def _get_collection(self, table_type, *args, **kwargs):
                    if table_type == "runs":
                        raise RuntimeError("runs collection unavailable")
                    return super()._get_collection(table_type, *args, **kwargs)

        db.__class__ = Failing

    with pytest.raises(Exception, match="runs collection unavailable"):
        calculate(b, ns, patch=patch)


@pytest.mark.parametrize("backend", MONGO_BACKENDS)
def test_mongo_metrics_raise_when_first_session_date_cannot_be_read(ns, backend):
    b = BACKENDS[backend]
    seed(b, ns, table_run_sessions=1)

    def patch(db):
        base = type(db)

        # With no metrics yet, the starting date is the first session's, read through get_sessions
        if inspect.iscoroutinefunction(base.get_sessions):

            class Failing(base):  # type: ignore[valid-type,misc]
                async def get_sessions(self, *args, **kwargs):
                    raise RuntimeError("sessions collection unavailable")

        else:

            class Failing(base):  # type: ignore[valid-type,misc,no-redef]
                def get_sessions(self, *args, **kwargs):
                    raise RuntimeError("sessions collection unavailable")

        db.__class__ = Failing

    with pytest.raises(Exception, match="sessions collection unavailable"):
        calculate(b, ns, patch=patch)


# ---------------------------------------------------------------------------
# Memory is bounded by what metrics need, not by the legacy column
# ---------------------------------------------------------------------------

# Peak RSS is a process-wide high-water mark, so the refresh runs in a fresh process.
_CHILD = """
import resource, sys

sys.path.insert(0, sys.argv[1])
import test_metrics_adapters_scale_and_memory as t


def peak_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # macOS reports bytes, Linux KiB


backend = t.BACKENDS[sys.argv[2]]
before = peak_bytes()
result = t.calculate(backend, sys.argv[3])
print(sum(row["agent_runs_count"] for row in result or []))
print(peak_bytes() - before)
"""


@pytest.mark.parametrize("migrated", [True, False], ids=["migrated", "unmigrated"])
@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_refresh_memory_does_not_grow_with_the_legacy_column(ns, backend, migrated):
    payload = seed(BACKENDS[backend], ns, legacy_sessions=LARGE_SESSIONS, run_bytes=RUN_BYTES, migrated=migrated)

    done = subprocess.run(
        [sys.executable, "-c", _CHILD, os.path.dirname(__file__), backend, ns],
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert done.returncode == 0, done.stderr[-2000:]
    runs_counted, growth = (int(line) for line in done.stdout.strip().splitlines()[-2:])
    assert runs_counted == LARGE_SESSIONS * RUNS_PER_SESSION
    assert growth < payload * MAX_GROWTH_FRACTION, (
        f"{backend} metrics refresh grew peak memory by {growth / 1e6:.0f} MB with "
        f"{payload / 1e6:.0f} MB of legacy runs; the refresh is loading the legacy runs column"
    )
