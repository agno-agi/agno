"""A metrics refresh on Redis, Valkey, DynamoDB, Firestore and SurrealDB must not hold whole runs in memory.

These stores return whole records, so each run is reduced to its model and provider as it is read:

- Legacy runs, kept on session records by the v3.0.0 migration until cleanup_legacy_runs_field() is
  called, are not held for every session in the refresh at once.
- Runs-table rows, which carry each run's full output, are not held for every session at once either.
- Runs are still counted once whether they live in the runs table, only on the session record, or both.
- A failed read surfaces as an error instead of a refresh with missing sessions or zero runs.

Runs against live servers (Redis on 6379, a Redis Cluster on 7100, Valkey on 6380, DynamoDB Local on 8001,
the Firestore emulator on 8080, SurrealDB on 8000) with a unique namespace per test; an absent server is skipped.
"""

import json
import os
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import pytest

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")

from agno.metrics import RunMetrics  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.session.agent import AgentSession  # noqa: E402

REDIS_URL = "redis://localhost:6379"
REDIS_CLUSTER_PORT = 7100
VALKEY_PORT = 6380
DYNAMO_ENDPOINT = "http://localhost:8001"
FIRESTORE_PROJECT = "agno-test"
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_CREDS = {"username": "root", "password": "root"}

RUNS_PER_SESSION = 10
SMALL_SESSIONS = 5
# ~60 MB of runs JSON: far above what a refresh needs, within a CI runner's memory and DynamoDB's
# 400 KB item limit (10 runs x 20 KB per session).
LARGE_SESSIONS = 300
RUN_BYTES = 20_000
# Holding every run costs the whole payload (>1x); reading model and provider per record costs a fraction.
MAX_GROWTH_FRACTION = 0.5


def _created_at() -> int:
    return int(time.time()) - 86400


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _redis_client(port: int):
    import redis

    return redis.Redis(host="localhost", port=port, socket_connect_timeout=2)


def _key_value_reachable(port: int) -> Callable[[], bool]:
    def probe() -> bool:
        try:
            return bool(_redis_client(port).ping())
        except Exception:
            return False

    return probe


def _drop_key_value(port: int) -> Callable[[str], None]:
    def drop(ns: str) -> None:
        client = _redis_client(port)
        keys = list(client.scan_iter(match=f"{ns}:*", count=1000))
        for start in range(0, len(keys), 1000):
            client.delete(*keys[start : start + 1000])

    return drop


def _redis_cluster_client():
    from redis.cluster import RedisCluster

    return RedisCluster(host="localhost", port=REDIS_CLUSTER_PORT, socket_connect_timeout=2)


def _redis_cluster_reachable() -> bool:
    try:
        return bool(_redis_cluster_client().ping())
    except Exception:
        return False


def _drop_redis_cluster(ns: str) -> None:
    client = _redis_cluster_client()
    # One key per DELETE: keys of a namespace hash to different slots, on different nodes
    for key in list(client.scan_iter(match=f"{ns}:*", count=1000)):
        client.delete(key)


def _dynamo_client():
    import boto3

    return boto3.client(
        "dynamodb",
        endpoint_url=DYNAMO_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


def _dynamo_reachable() -> bool:
    try:
        _dynamo_client().list_tables()
        return True
    except Exception:
        return False


def _drop_dynamo(ns: str) -> None:
    client = _dynamo_client()
    for name in client.list_tables()["TableNames"]:
        if name.startswith(ns):
            client.delete_table(TableName=name)


def _firestore_client():
    from google.cloud import firestore

    return firestore.Client(project=FIRESTORE_PROJECT)


def _firestore_reachable() -> bool:
    import socket

    try:
        socket.create_connection(("localhost", 8080), timeout=2).close()
        return True
    except Exception:
        return False


def _drop_firestore(ns: str) -> None:
    client = _firestore_client()
    for suffix in ("sessions", "runs", "metrics"):
        for doc in client.collection(f"{ns}_{suffix}").stream():
            doc.reference.delete()


def _surreal_client():
    from surrealdb import Surreal

    client = Surreal(SURREALDB_URL)
    client.signin(SURREALDB_CREDS)
    return client


def _surreal_reachable() -> bool:
    try:
        _surreal_client()
        return True
    except Exception:
        return False


def _drop_surreal(ns: str) -> None:
    client = _surreal_client()
    client.use("agno", ns)
    client.query(f"REMOVE DATABASE IF EXISTS {ns}")


def _make_redis(ns: str):
    from agno.db.redis import RedisDb

    return RedisDb(db_url=REDIS_URL, db_prefix=ns)


def _make_redis_cluster(ns: str):
    from agno.db.redis import RedisDb

    return RedisDb(redis_client=_redis_cluster_client(), db_prefix=ns)


def _make_valkey(ns: str):
    from agno.db.valkey import ValkeyDb

    return ValkeyDb(host="localhost", port=VALKEY_PORT, db_prefix=ns)


def _make_dynamo(ns: str):
    from agno.db.dynamo import DynamoDb

    return DynamoDb(
        db_client=_dynamo_client(),
        session_table=f"{ns}_sessions",
        runs_table=f"{ns}_runs",
        metrics_table=f"{ns}_metrics",
    )


def _make_firestore(ns: str):
    from agno.db.firestore import FirestoreDb

    return FirestoreDb(
        db_client=_firestore_client(),
        session_collection=f"{ns}_sessions",
        runs_collection=f"{ns}_runs",
        metrics_collection=f"{ns}_metrics",
    )


def _make_surreal(ns: str):
    from agno.db.surrealdb import SurrealDb

    return SurrealDb(None, SURREALDB_URL, SURREALDB_CREDS, "agno", ns)


def _set_legacy_key_value(db, session_id: str, runs: List[Dict[str, Any]]) -> None:
    record = db._get_record("sessions", session_id)
    record["runs"] = runs
    db._store_record("sessions", session_id, record)


def _set_legacy_dynamo(db, session_id: str, runs: List[Dict[str, Any]]) -> None:
    db.client.update_item(
        TableName=db._get_table("sessions"),
        Key={"session_id": {"S": session_id}},
        UpdateExpression="SET #runs = :runs",
        ExpressionAttributeNames={"#runs": "runs"},
        ExpressionAttributeValues={":runs": {"S": json.dumps(runs)}},
    )


def _set_legacy_firestore(db, session_id: str, runs: List[Dict[str, Any]]) -> None:
    from google.cloud.firestore_v1.base_query import FieldFilter

    for doc in db._get_collection("sessions").where(filter=FieldFilter("session_id", "==", session_id)).stream():
        doc.reference.update({"runs": runs})


def _set_legacy_surreal(db, session_id: str, runs: List[Dict[str, Any]]) -> None:
    from surrealdb import RecordID

    # SurrealDB keys a session by its record id; there is no session_id field to match on
    db.client.query(
        "UPDATE $record SET runs = $runs", {"record": RecordID(db._get_table("sessions"), session_id), "runs": runs}
    )


class Backend:
    def __init__(
        self,
        name: str,
        make: Callable[[str], Any],
        set_legacy: Callable[[Any, str, List[Dict[str, Any]]], None],
        reachable: Callable[[], bool],
        drop: Callable[[str], None],
    ):
        self.name = name
        self.make = make
        self.set_legacy = set_legacy
        self.reachable = reachable
        self.drop = drop


BACKENDS: Dict[str, Backend] = {
    b.name: b
    for b in [
        Backend("redis", _make_redis, _set_legacy_key_value, _key_value_reachable(6379), _drop_key_value(6379)),
        Backend(
            "redis_cluster",
            _make_redis_cluster,
            _set_legacy_key_value,
            _redis_cluster_reachable,
            _drop_redis_cluster,
        ),
        Backend(
            "valkey",
            _make_valkey,
            _set_legacy_key_value,
            _key_value_reachable(VALKEY_PORT),
            _drop_key_value(VALKEY_PORT),
        ),
        Backend("dynamo", _make_dynamo, _set_legacy_dynamo, _dynamo_reachable, _drop_dynamo),
        Backend("firestore", _make_firestore, _set_legacy_firestore, _firestore_reachable, _drop_firestore),
        Backend("surrealdb", _make_surreal, _set_legacy_surreal, _surreal_reachable, _drop_surreal),
    ]
}


@pytest.fixture
def ns(request):
    backend = BACKENDS[request.node.callspec.params["backend"]]
    if not backend.reachable():
        pytest.skip(f"{backend.name} server not reachable")
    name = f"metrics{uuid.uuid4().hex[:8]}"
    yield name
    backend.drop(name)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _run(session_id: str, index: int, run_bytes: int, provider: bool = True) -> RunOutput:
    return RunOutput(
        run_id=f"{session_id}_r{index}",
        agent_id="a1",
        session_id=session_id,
        user_id="u1",
        model="gpt-5.5",
        model_provider="OpenAI" if provider else None,
        content=uuid.uuid4().hex * max(run_bytes // 32, 1),
        status=RunStatus.completed,
        created_at=_created_at() + index,
        metrics=RunMetrics(input_tokens=1, output_tokens=1, total_tokens=2),
    )


def seed(
    backend: Backend,
    ns: str,
    sessions: int,
    first: int = 1,
    run_bytes: int = 1_000,
    legacy: bool = True,
    table_runs: bool = False,
    provider: bool = True,
    runs_per_session: int = RUNS_PER_SESSION,
) -> int:
    """Add agent sessions created yesterday; return the bytes of runs JSON they carry.

    ``legacy`` keeps each session's runs on its record, as 2.x stored them; ``table_runs`` writes them
    to the runs table, as v3 and the migration do. Both together is a migrated session whose legacy
    field has not been cleaned up.
    """
    db = backend.make(ns)
    payload = 0
    for s in range(first, first + sessions):
        session_id = f"s{s}"
        runs = [_run(session_id, r, run_bytes, provider) for r in range(runs_per_session)]
        db.upsert_session(
            AgentSession(
                session_id=session_id,
                agent_id="a1",
                user_id="u1",
                created_at=_created_at(),
                session_data={"session_metrics": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}},
            )
        )
        payload += len(json.dumps([run.to_dict() for run in runs]))
        if legacy:
            backend.set_legacy(db, session_id, [run.to_dict() for run in runs])
        if table_runs:
            for index, run in enumerate(runs):
                db.upsert_run(run, session_id=session_id, user_id="u1", run_index=index)
    return payload


def calculate(backend: Backend, ns: str, patch: Optional[Callable[[Any], None]] = None) -> Optional[List[dict]]:
    db = backend.make(ns)
    if patch is not None:
        patch(db)
    return db.calculate_metrics()


def _model_metrics(result: List[dict]) -> List[tuple]:
    return sorted((m["model_id"], m["model_provider"], m["count"]) for m in result[0]["model_metrics"])


# ---------------------------------------------------------------------------
# Every run is counted once, wherever it is stored
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_count_migrated_unmigrated_and_v3_runs_once(ns, backend):
    """Migrated sessions count from the runs table, unmigrated ones from the session record, v3 ones have none."""
    b = BACKENDS[backend]
    seed(b, ns, SMALL_SESSIONS, table_runs=True)
    seed(b, ns, SMALL_SESSIONS, first=SMALL_SESSIONS + 1)
    # A legacy run without a provider is reported under an empty provider
    seed(b, ns, 1, first=2 * SMALL_SESSIONS + 1, provider=False)
    b.make(ns).upsert_session(AgentSession(session_id="v3", agent_id="a1", user_id="u1", created_at=_created_at()))

    result = calculate(b, ns)

    assert result is not None and len(result) == 1
    tracked_runs = 2 * SMALL_SESSIONS * RUNS_PER_SESSION
    assert result[0]["agent_sessions_count"] == 2 * SMALL_SESSIONS + 2
    assert result[0]["agent_runs_count"] == tracked_runs + RUNS_PER_SESSION
    assert _model_metrics(result) == [("gpt-5.5", "", RUNS_PER_SESSION), ("gpt-5.5", "OpenAI", tracked_runs)]


@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_start_from_the_first_session_of_any_type(ns, backend):
    """A store with no agent sessions still gets metrics: the first refresh starts at its first session of any type."""
    from agno.session.team import TeamSession

    b = BACKENDS[backend]
    b.make(ns).upsert_session(TeamSession(session_id="t1", team_id="team-1", user_id="u1", created_at=_created_at()))

    result = calculate(b, ns)

    assert result is not None and len(result) == 1
    assert result[0]["team_sessions_count"] == 1


# What each adapter reported, before runs were reduced as read, for a runs-table run without a provider
PROVIDERLESS_TABLE_RUN = {
    "redis": "None",
    "redis_cluster": "None",
    "valkey": "None",
    "dynamo": "",
    "firestore": "None",
    "surrealdb": "",
}


@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_report_a_providerless_table_run_as_before(ns, backend):
    b = BACKENDS[backend]
    seed(b, ns, 1, legacy=False, table_runs=True, provider=False)

    result = calculate(b, ns)

    assert _model_metrics(result) == [("gpt-5.5", PROVIDERLESS_TABLE_RUN[backend], RUNS_PER_SESSION)]


# ---------------------------------------------------------------------------
# A failed read surfaces as an error
# ---------------------------------------------------------------------------


def _fail_runs_reads(db) -> None:
    """Make every read of the runs table fail at the client, below the adapter."""

    class Boom(RuntimeError):
        pass

    def failing(method: Callable, is_runs: Callable[..., bool]) -> Callable:
        def wrapper(*args, **kwargs):
            if is_runs(*args, **kwargs):
                raise Boom("runs read failed")
            return method(*args, **kwargs)

        return wrapper

    name = type(db).__name__
    if name == "RedisDb":
        db.redis_client.zrange = failing(db.redis_client.zrange, lambda key, *a, **k: True)
    elif name == "ValkeyDb":
        db.valkey_client.zrange = failing(db.valkey_client.zrange, lambda key, *a, **k: True)
    elif name == "DynamoDb":
        runs_table = db._get_table("runs")
        db.client.query = failing(db.client.query, lambda **k: k.get("TableName") == runs_table)
    elif name == "FirestoreDb":
        runs_name = db._get_collection("runs").id
        db.db_client.collection = failing(db.db_client.collection, lambda path, *a, **k: path == runs_name)
    elif name == "SurrealDb":
        runs_table = db._get_table("runs")
        db._query = failing(db._query, lambda query, *a, **k: runs_table in query)


@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_raise_when_runs_cannot_be_read(ns, backend):
    b = BACKENDS[backend]
    seed(b, ns, 1, table_runs=True, legacy=False)

    with pytest.raises(Exception, match="runs read failed"):
        calculate(b, ns, patch=_fail_runs_reads)


def _fail_session_reads(db) -> None:
    """Make every read of the sessions table fail at the client, below the adapter."""

    def boom(*args, **kwargs):
        raise RuntimeError("sessions read failed")

    name = type(db).__name__
    if name == "RedisDb":
        db.redis_client.get = boom
        db.redis_client.pipeline = boom
    elif name == "ValkeyDb":
        db._exec_pipeline = boom
    elif name == "DynamoDb":
        db.client.query = boom
        db.client.scan = boom
    elif name == "FirestoreDb":
        db.db_client.collection = boom
    elif name == "SurrealDb":
        sessions_table = db._get_table("sessions")
        query = db.client.query

        def failing_select(statement, *args, **kwargs):
            if "SELECT" in statement and sessions_table in statement:
                boom()
            return query(statement, *args, **kwargs)

        db.client.query = failing_select


@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_raise_when_sessions_cannot_be_read(ns, backend):
    b = BACKENDS[backend]
    seed(b, ns, 1, table_runs=True, legacy=False)

    # SurrealDB's query helper rewraps failures as "Query execution error", dropping the original message
    with pytest.raises(Exception, match="sessions read failed|Query execution error"):
        calculate(b, ns, patch=_fail_session_reads)


# ---------------------------------------------------------------------------
# Memory is bounded by what metrics need, not by the runs
# ---------------------------------------------------------------------------

# Peak RSS is a process-wide high-water mark, so the refresh runs in a fresh process.
_CHILD = """
import resource, sys

sys.path.insert(0, sys.argv[1])
import test_metrics_nosql_adapters_memory_and_errors as t


def peak_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # macOS reports bytes, Linux KiB


backend = t.BACKENDS[sys.argv[2]]
db = backend.make(sys.argv[3])
before = peak_bytes()
result = db.calculate_metrics()
print(sum(row["agent_runs_count"] for row in result or []))
print(peak_bytes() - before)
"""

STATES = {
    # Legacy runs only on the session records
    "unmigrated": dict(legacy=True, table_runs=False),
    # Migrated, legacy field not yet cleaned up: runs in both places
    "migrated": dict(legacy=True, table_runs=True),
    # After cleanup_legacy_runs_field(): runs only in the runs table, each with its full output
    "cleaned": dict(legacy=False, table_runs=True),
}


@pytest.mark.parametrize("state", list(STATES))
@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_refresh_memory_does_not_grow_with_the_runs(ns, backend, state):
    payload = seed(BACKENDS[backend], ns, LARGE_SESSIONS, run_bytes=RUN_BYTES, **STATES[state])

    done = subprocess.run(
        [sys.executable, "-c", _CHILD, os.path.dirname(__file__), backend, ns],
        capture_output=True,
        text=True,
        timeout=900,
    )

    assert done.returncode == 0, done.stderr[-2000:]
    runs_counted, growth = (int(line) for line in done.stdout.strip().splitlines()[-2:])
    assert runs_counted == LARGE_SESSIONS * RUNS_PER_SESSION
    assert growth < payload * MAX_GROWTH_FRACTION, (
        f"{backend} metrics refresh grew peak memory by {growth / 1e6:.0f} MB with "
        f"{payload / 1e6:.0f} MB of runs; the refresh is holding whole runs"
    )


# One session with as many runs as all of LARGE_SESSIONS have together
RUNS_IN_ONE_LARGE_SESSION = LARGE_SESSIONS * RUNS_PER_SESSION


@pytest.mark.parametrize("backend", list(BACKENDS))
def test_metrics_refresh_memory_does_not_grow_with_one_large_session(ns, backend):
    """A session's runs are reduced as they are read, not held whole until the session is done."""
    payload = seed(
        BACKENDS[backend],
        ns,
        1,
        run_bytes=RUN_BYTES,
        legacy=False,
        table_runs=True,
        runs_per_session=RUNS_IN_ONE_LARGE_SESSION,
    )

    done = subprocess.run(
        [sys.executable, "-c", _CHILD, os.path.dirname(__file__), backend, ns],
        capture_output=True,
        text=True,
        timeout=900,
    )

    assert done.returncode == 0, done.stderr[-2000:]
    runs_counted, growth = (int(line) for line in done.stdout.strip().splitlines()[-2:])
    assert runs_counted == RUNS_IN_ONE_LARGE_SESSION
    assert growth < payload * MAX_GROWTH_FRACTION, (
        f"{backend} metrics refresh grew peak memory by {growth / 1e6:.0f} MB for one session with "
        f"{payload / 1e6:.0f} MB of runs; the session's runs are held whole"
    )
