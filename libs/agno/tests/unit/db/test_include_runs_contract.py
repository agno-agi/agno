"""Cross-adapter tests for ``get_sessions(include_runs=False)`` and the
AgentOS service-layer wiring that relies on it.

The DB-layer parameter was added with the v3.0 runs-store split so list-type
reads would not have to pull full run history; ``get_sessions_page()`` (the
shared funnel for REST ``GET /sessions`` and the MCP ``get_sessions`` tool)
now passes ``include_runs=False``. These tests pin the contract across the
adapter matrix:

- every concrete adapter's ``get_sessions`` ACCEPTS the kwarg (12 previously
  violated their own abstract-signature contract and raised ``TypeError``);
- skipping leaves ``runs`` unset (``None``) on returned dicts and storage
  untouched (a single ``get_session`` still returns the runs);
- the default (``include_runs=True``) still attaches runs, preserving the
  pre-existing behavior for direct callers;
- the service funnel forwards the skip.

Covered here with in-process instances (per repo precedent — the migration
compat suites use the same stubs): SqliteDb, InMemoryDb, JsonDb. The remaining
adapters are pinned by signature inspection (they share the exact attach
shape exercised by the in-process trio) — running live MySQL/Mongo/Redis/
Firestore/Dynamo/SurrealDB/GCS instances in unit tests is not repo practice.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import List

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.json.json_db import JsonDb
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

COMPLETED = [("r0", "COMPLETED"), ("r1", "COMPLETED"), ("r2", "COMPLETED")]


def _ids(runs) -> List[str]:
    return [r.run_id if hasattr(r, "run_id") else r.get("run_id") for r in (runs or [])]


def _seeded_sqlite() -> SqliteDb:
    import tempfile

    db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
    sess = AgentSession(session_id="s1", agent_id="a1")
    for rid, status in COMPLETED:
        sess.upsert_run(RunOutput(run_id=rid, agent_id="a1", status=RunStatus(status)))
    db.upsert_session(sess)
    for i, (rid, status) in enumerate(COMPLETED):
        db.upsert_run(
            RunOutput(run_id=rid, agent_id="a1", status=RunStatus(status)),
            session_id="s1",
            user_id=None,
            run_index=i,
        )
    return db


def _seeded_in_memory() -> InMemoryDb:
    db = InMemoryDb()
    sess = AgentSession(session_id="s1", agent_id="a1")
    for rid, status in COMPLETED:
        sess.upsert_run(RunOutput(run_id=rid, agent_id="a1", status=RunStatus(status)))
    db.upsert_session(sess)
    for i, (rid, status) in enumerate(COMPLETED):
        db.upsert_run(
            RunOutput(run_id=rid, agent_id="a1", status=RunStatus(status)),
            session_id="s1",
            user_id=None,
            run_index=i,
        )
    return db


def _seeded_json() -> JsonDb:
    import tempfile

    db = JsonDb(db_path=tempfile.mkdtemp())
    sess = AgentSession(session_id="s1", agent_id="a1")
    for rid, status in COMPLETED:
        sess.upsert_run(RunOutput(run_id=rid, agent_id="a1", status=RunStatus(status)))
    db.upsert_session(sess)
    for i, (rid, status) in enumerate(COMPLETED):
        db.upsert_run(
            RunOutput(run_id=rid, agent_id="a1", status=RunStatus(status)),
            session_id="s1",
            user_id=None,
            run_index=i,
        )
    return db


# ---------------------------------------------------------------------------
# Adapter contract: the kwarg is accepted and behaves identically everywhere
# ---------------------------------------------------------------------------

ADAPTERS = [
    ("sqlite", _seeded_sqlite),
    ("in_memory", _seeded_in_memory),
    ("json", _seeded_json),
]


class TestIncludeRunsAcrossAdapters:
    @pytest.mark.parametrize("name,make_db", ADAPTERS, ids=[n for n, _ in ADAPTERS])
    def test_include_runs_false_omits_runs(self, name, make_db):
        db = make_db()
        sessions, _ = db.get_sessions(deserialize=False, include_runs=False)
        assert len(sessions) == 1
        assert sessions[0]["runs"] is None
        # Storage untouched — a single get_session still returns the runs.
        assert _ids(db.get_session("s1", deserialize=False)["runs"]) == ["r0", "r1", "r2"]

    @pytest.mark.parametrize("name,make_db", ADAPTERS, ids=[n for n, _ in ADAPTERS])
    def test_default_attaches_runs(self, name, make_db):
        db = make_db()
        sessions, _ = db.get_sessions(deserialize=False)
        assert _ids(sessions[0]["runs"]) == ["r0", "r1", "r2"]

    @pytest.mark.parametrize("name,make_db", ADAPTERS, ids=[n for n, _ in ADAPTERS])
    def test_deserialized_sessions_work_without_runs(self, name, make_db):
        # deserialize=True path: Session objects must construct fine with runs skipped.
        db = make_db()
        sessions = db.get_sessions(deserialize=True, include_runs=False)
        assert len(sessions) == 1
        assert sessions[0].runs is None or sessions[0].runs == []


# Every concrete adapter that declares get_sessions must accept include_runs —
# 12 of them previously violated their own abstract-signature contract
# (BaseDb.get_sessions declares the parameter) and raised TypeError.
# Checked STATICALLY (source scan) so the test runs regardless of optional
# client libraries (boto3, google-cloud-firestore, valkey-glide, surrealdb,
# gcs deps are not unit-test requirements); when a module DOES import cleanly
# the live signature is inspected as well.
ADAPTER_FILES_WITH_GET_SESSIONS = [
    ("agno.db.mysql.mysql", "MySQLDb", "db/mysql/mysql.py"),
    ("agno.db.mysql.async_mysql", "AsyncMySQLDb", "db/mysql/async_mysql.py"),
    ("agno.db.mongo.mongo", "MongoDb", "db/mongo/mongo.py"),
    ("agno.db.mongo.async_mongo", "AsyncMongoDb", "db/mongo/async_mongo.py"),
    ("agno.db.redis.redis", "RedisDb", "db/redis/redis.py"),
    ("agno.db.valkey.valkey", "ValkeyDb", "db/valkey/valkey.py"),
    ("agno.db.firestore.firestore", "FirestoreDb", "db/firestore/firestore.py"),
    ("agno.db.dynamo.dynamo", "DynamoDb", "db/dynamo/dynamo.py"),
    ("agno.db.singlestore.singlestore", "SingleStoreDb", "db/singlestore/singlestore.py"),
    ("agno.db.surrealdb.surrealdb", "SurrealDb", "db/surrealdb/surrealdb.py"),
    ("agno.db.gcs_json.gcs_json_db", "GcsJsonDb", "db/gcs_json/gcs_json_db.py"),
    ("agno.db.json.json_db", "JsonDb", "db/json/json_db.py"),
]


def _adapter_module_dir(module_path: str, rel_file: str) -> str:
    from pathlib import Path

    import agno

    return str(Path(agno.__file__).parent / rel_file)


class TestAdapterSignatureContract:
    @pytest.mark.parametrize("module_path,class_name,rel_file", ADAPTER_FILES_WITH_GET_SESSIONS)
    def test_get_sessions_accepts_include_runs(self, module_path, class_name, rel_file):
        # Static source check: the parameter must appear inside the get_sessions
        # signature block of the adapter source. Works without optional deps.
        import re

        source = open(_adapter_module_dir(module_path, rel_file)).read()
        match = re.search(
            r"def get_sessions\(.*?\)\s*->",
            source,
            re.DOTALL,
        )
        assert match, f"{class_name}: could not locate get_sessions signature"
        assert "include_runs" in match.group(0), (
            f"{class_name}.get_sessions must accept include_runs "
            "(BaseDb.get_sessions declares it; AgentOS list views pass it)"
        )

        # Live check when the module imports without its optional client lib.
        try:
            import importlib

            module = importlib.import_module(module_path)
            sig = inspect.signature(getattr(module, class_name).get_sessions)
            assert "include_runs" in sig.parameters
            assert sig.parameters["include_runs"].default is True
        except (ImportError, ModuleNotFoundError):
            pytest.skip(f"optional client library not installed for {class_name}; static check passed")


# ---------------------------------------------------------------------------
# Service layer: get_sessions_page forwards the skip
# ---------------------------------------------------------------------------


class TestGetSessionsPageSkipsRuns:
    def test_service_funnel_forwards_include_runs_false(self):
        from agno.os.services.sessions import get_sessions_page

        db = _seeded_in_memory()
        sessions, total = asyncio.run(get_sessions_page(db, session_type="agent", limit=20, page=1))
        assert total == 1
        assert sessions[0]["runs"] is None
        # And the underlying storage is untouched — get_session still attaches.
        assert _ids(db.get_session("s1", deserialize=False)["runs"]) == ["r0", "r1", "r2"]

    def test_list_view_renders_nameless_session_as_empty_name(self):
        # DOCUMENTED BEHAVIOR CHANGE (issue + PR bodies): sessions without a
        # stored session_data.session_name used to get a run-derived fallback
        # name at list time; with runs skipped on list views that fallback is
        # intentionally unavailable, so SessionSchema renders "".
        from agno.os.schema import SessionSchema

        db = _seeded_in_memory()
        sessions, _ = db.get_sessions(deserialize=False, include_runs=False)
        rendered = SessionSchema.from_dict(sessions[0])
        assert rendered.session_name == ""
