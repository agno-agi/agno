"""Unit tests for ValkeyDb session store with mocked GLIDE client.

These tests validate the session store logic without requiring a running Valkey instance,
matching the pattern used for the vector store tests in tests/unit/vectordb/test_valkeydb.py.
"""

import json
import sys
import time
import types
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest


def _ensure_glide_sync_stub():
    """Install a glide_sync stub module with real classes for isinstance checks."""
    if "glide_sync" in sys.modules:
        # Module already exists — ensure our extra attributes are present
        glide_mod = sys.modules["glide_sync"]
        _patch_missing_attrs(glide_mod)
        return

    glide_mod = types.ModuleType("glide_sync")

    # Real classes so isinstance() works
    class _GlideClient:
        @classmethod
        def create(cls, config):
            return cls()

        def get(self, key):
            return None

        def set(self, key, value):
            pass

        def delete(self, keys):
            return 0

        def scan(self, cursor="0", match=None, count=None):
            return ("0", [])

        def smembers(self, key):
            return set()

        def srem(self, key, members):
            return 0

        def sadd(self, key, members):
            return 0

        def exec(self, pipeline, raise_on_error=False):
            return []

    class _GlideClusterClient:
        pass

    class _Batch:
        def __init__(self, is_atomic=False):
            self.commands = []

        def get(self, key):
            self.commands.append(("get", key))

        def set(self, key, value):
            self.commands.append(("set", key, value))

        def delete(self, keys):
            self.commands.append(("delete", keys))

        def srem(self, key, members):
            self.commands.append(("srem", key, members))

        def sadd(self, key, members):
            self.commands.append(("sadd", key, members))

    class _ClusterBatch:
        def __init__(self, is_atomic=False):
            pass

    class _ClusterScanCursor:
        def is_finished(self):
            return True

    class _NodeAddress:
        def __init__(self, host="localhost", port=6379):
            self.host = host
            self.port = port

    class _GlideClientConfiguration:
        def __init__(self, addresses=None, database_id=None, credentials=None, use_tls=False):
            pass

    class _ServerCredentials:
        def __init__(self, password=None, username=None):
            pass

    class _ExpirySet:
        def __init__(self, expiry_type=None, value=None):
            pass

    class _ExpiryType:
        SEC = "SEC"

    glide_mod.GlideClient = _GlideClient
    glide_mod.GlideClusterClient = _GlideClusterClient
    glide_mod.Batch = _Batch
    glide_mod.ClusterBatch = _ClusterBatch
    glide_mod.ClusterScanCursor = _ClusterScanCursor
    glide_mod.NodeAddress = _NodeAddress
    glide_mod.GlideClientConfiguration = _GlideClientConfiguration
    glide_mod.ServerCredentials = _ServerCredentials
    glide_mod.ExpirySet = _ExpirySet
    glide_mod.ExpiryType = _ExpiryType
    glide_mod.DataType = MagicMock(name="DataType")

    # Also add stubs for vector store imports so both test files can coexist
    for attr in (
        "DistanceMetricType",
        "FtCreateOptions",
        "FtSearchLimit",
        "FtSearchOptions",
        "ReturnField",
        "TagField",
        "TextField",
        "VectorAlgorithm",
        "VectorField",
        "VectorFieldAttributesFlat",
        "VectorFieldAttributesHnsw",
        "VectorType",
    ):
        setattr(glide_mod, attr, MagicMock(name=attr))

    glide_mod.ft = MagicMock(name="glide_ft_module")  # type: ignore[attr-defined]

    sys.modules["glide_sync"] = glide_mod


def _patch_missing_attrs(glide_mod):
    """Ensure all needed attributes exist on an already-loaded glide_sync stub."""
    needed = (
        "Batch",
        "ClusterBatch",
        "ClusterScanCursor",
        "DataType",
        "ExpirySet",
        "ExpiryType",
        "GlideClient",
        "GlideClientConfiguration",
        "GlideClusterClient",
        "NodeAddress",
        "ServerCredentials",
        "DistanceMetricType",
        "FtCreateOptions",
        "FtSearchLimit",
        "FtSearchOptions",
        "ReturnField",
        "TagField",
        "TextField",
        "VectorAlgorithm",
        "VectorField",
        "VectorFieldAttributesFlat",
        "VectorFieldAttributesHnsw",
        "VectorType",
    )
    for attr in needed:
        if not hasattr(glide_mod, attr):
            setattr(glide_mod, attr, MagicMock(name=attr))
    if not hasattr(glide_mod, "ft"):
        glide_mod.ft = MagicMock(name="glide_ft_module")  # type: ignore[attr-defined]


_ensure_glide_sync_stub()

from agno.db.valkey.valkey import ValkeyDb  # noqa: E402


@pytest.fixture()
def mock_client():
    """Create a mock that passes isinstance(client, GlideClient) checks."""
    from glide_sync import GlideClient

    client = MagicMock(spec=GlideClient)
    # Default scan returns empty (cursor "0", no keys)
    client.scan.return_value = ("0", [])
    client.smembers.return_value = set()
    return client


@pytest.fixture()
def valkey_db(mock_client):
    """Create a ValkeyDb instance with a mocked GLIDE client."""
    db = ValkeyDb(
        valkey_client=mock_client,
        db_prefix="test",
        session_table="sessions",
        memory_table="memories",
        metrics_table="metrics",
        eval_table="evals",
        knowledge_table="knowledge",
        culture_table="culture",
        traces_table="traces",
        spans_table="spans",
    )
    return db


def _make_session_data(session_id: str, **overrides: Any) -> Dict[str, Any]:
    """Helper to build a session record."""
    now = int(time.time())
    data: Dict[str, Any] = {
        "session_id": session_id,
        "session_type": "agent",
        "agent_id": overrides.get("agent_id", "agent-1"),
        "team_id": overrides.get("team_id"),
        "workflow_id": overrides.get("workflow_id"),
        "user_id": overrides.get("user_id", "user-1"),
        "session_data": overrides.get("session_data", {}),
        "agent_data": overrides.get("agent_data", {}),
        "team_data": overrides.get("team_data"),
        "workflow_data": overrides.get("workflow_data"),
        "metadata": overrides.get("metadata", {}),
        "runs": overrides.get("runs", []),
        "summary": overrides.get("summary"),
        "created_at": overrides.get("created_at", now),
        "updated_at": overrides.get("updated_at", now),
    }
    return data


def _serialize(data: Dict[str, Any]) -> str:
    return json.dumps(data)


def _make_trace_data(trace_id: str, **overrides: Any) -> Dict[str, Any]:
    """Helper to build a trace record."""
    return {
        "trace_id": trace_id,
        "name": overrides.get("name", "test-trace"),
        "status": overrides.get("status", "OK"),
        "duration_ms": overrides.get("duration_ms", 100),
        "run_id": overrides.get("run_id", "r1"),
        "session_id": overrides.get("session_id", "s1"),
        "user_id": overrides.get("user_id", "u1"),
        "agent_id": overrides.get("agent_id", "a1"),
        "team_id": overrides.get("team_id"),
        "workflow_id": overrides.get("workflow_id"),
        "start_time": overrides.get("start_time", "2026-01-01T00:00:00Z"),
        "end_time": overrides.get("end_time", "2026-01-01T00:00:01Z"),
        "created_at": overrides.get("created_at", "2026-01-01T00:00:00Z"),
    }


# -- Session CRUD tests --


class TestSessionCRUD:
    def test_get_session_returns_none_when_missing(self, valkey_db, mock_client):
        mock_client.get.return_value = None
        result = valkey_db.get_session(session_id="nonexistent", session_type="agent")
        assert result is None

    def test_get_session_returns_data(self, valkey_db, mock_client):
        session_data = _make_session_data("sess-1")
        mock_client.get.return_value = _serialize(session_data)

        result = valkey_db.get_session(session_id="sess-1", session_type="agent", deserialize=False)
        assert result is not None
        assert result.get("session_id") == "sess-1"

    def test_delete_session(self, valkey_db, mock_client):
        session_data = _make_session_data("sess-3")
        mock_client.get.return_value = _serialize(session_data)
        mock_client.delete.return_value = 1

        result = valkey_db.delete_session(session_id="sess-3")
        assert result is True

    def test_delete_session_not_found(self, valkey_db, mock_client):
        mock_client.get.return_value = None
        mock_client.delete.return_value = 0
        result = valkey_db.delete_session(session_id="nonexistent")
        assert result is False


# -- Memory tests --


class TestMemory:
    def test_get_all_memory_topics_empty(self, valkey_db, mock_client):
        mock_client.scan.return_value = ("0", [])
        topics = valkey_db.get_all_memory_topics()
        assert topics == []

    def test_get_all_memory_topics_extracts_topics(self, valkey_db, mock_client):
        mem1 = {"memory_id": "m1", "topics": ["cooking", "health"], "user_id": "u1"}
        mem2 = {"memory_id": "m2", "topics": ["cooking", "travel"], "user_id": "u1"}

        # Simulate scan returning memory keys, then cursor "0" to stop
        mock_client.scan.return_value = ("0", [b"test:memories:m1", b"test:memories:m2"])

        # _get_all_records uses pipeline batching: _create_pipeline + pipeline.get + _exec_pipeline
        mock_client.exec.return_value = [_serialize(mem1), _serialize(mem2)]

        topics = valkey_db.get_all_memory_topics()
        assert set(topics) == {"cooking", "health", "travel"}

    def test_get_all_memory_topics_filters_by_user_id(self, valkey_db, mock_client):
        mem1 = {"memory_id": "m1", "topics": ["cooking"], "user_id": "u1"}
        mem2 = {"memory_id": "m2", "topics": ["travel"], "user_id": "u2"}

        mock_client.scan.return_value = ("0", [b"test:memories:m1", b"test:memories:m2"])
        mock_client.exec.return_value = [_serialize(mem1), _serialize(mem2)]

        topics = valkey_db.get_all_memory_topics(user_id="u1")
        assert topics == ["cooking"]

    def test_delete_user_memory(self, valkey_db, mock_client):
        mem = {"memory_id": "m1", "topics": ["t1"], "user_id": "u1", "agent_id": "a1"}
        mock_client.get.return_value = _serialize(mem)
        mock_client.delete.return_value = 1

        valkey_db.delete_user_memory(memory_id="m1")
        assert mock_client.delete.called


# -- Schema version tests --


class TestSchemaVersion:
    def test_get_latest_schema_version_is_noop(self, valkey_db):
        result = valkey_db.get_latest_schema_version(table_name="sessions")
        assert result is None

    def test_upsert_schema_version_is_noop(self, valkey_db):
        # Should not raise
        valkey_db.upsert_schema_version(table_name="sessions", version="1.0.0")


# -- Trace tests --


class TestTrace:
    def test_get_trace_by_id(self, valkey_db, mock_client):
        trace_data = _make_trace_data("t1")
        mock_client.get.return_value = _serialize(trace_data)
        mock_client.smembers.return_value = set()

        result = valkey_db.get_trace(trace_id="t1")
        assert result is not None

    def test_get_trace_by_session_id(self, valkey_db, mock_client):
        trace_data = _make_trace_data("t1", session_id="s1")
        mock_client.scan.return_value = ("0", [b"test:traces:t1"])
        mock_client.exec.return_value = [_serialize(trace_data)]
        mock_client.smembers.return_value = set()

        result = valkey_db.get_trace(session_id="s1")
        assert result is not None

    def test_get_trace_by_user_id(self, valkey_db, mock_client):
        trace_data = _make_trace_data("t1", user_id="u1")
        mock_client.scan.return_value = ("0", [b"test:traces:t1"])
        mock_client.exec.return_value = [_serialize(trace_data)]
        mock_client.smembers.return_value = set()

        result = valkey_db.get_trace(user_id="u1")
        assert result is not None

    def test_get_trace_by_agent_id(self, valkey_db, mock_client):
        trace_data = _make_trace_data("t1", agent_id="a1")
        mock_client.scan.return_value = ("0", [b"test:traces:t1"])
        mock_client.exec.return_value = [_serialize(trace_data)]
        mock_client.smembers.return_value = set()

        result = valkey_db.get_trace(agent_id="a1")
        assert result is not None

    def test_get_trace_returns_none_when_missing(self, valkey_db, mock_client):
        mock_client.get.return_value = None
        result = valkey_db.get_trace(trace_id="nonexistent")
        assert result is None

    def test_get_trace_no_filters_returns_none(self, valkey_db):
        result = valkey_db.get_trace()
        assert result is None

    def test_get_traces_empty(self, valkey_db, mock_client):
        mock_client.scan.return_value = ("0", [])
        traces, count = valkey_db.get_traces()
        assert traces == []
        assert count == 0


# -- Knowledge tests --


class TestKnowledge:
    def test_get_knowledge_content_returns_none_when_missing(self, valkey_db, mock_client):
        mock_client.get.return_value = None
        result = valkey_db.get_knowledge_content(id="k1")
        assert result is None

    def test_delete_knowledge_content(self, valkey_db, mock_client):
        mock_client.get.return_value = _serialize({"id": "k1", "name": "test"})
        mock_client.delete.return_value = 1
        valkey_db.delete_knowledge_content(id="k1")
        assert mock_client.delete.called


# -- Table exists test --


class TestTableExists:
    def test_table_exists_always_true(self, valkey_db):
        # For key-value stores, tables always "exist"
        assert valkey_db.table_exists("sessions") is True
        assert valkey_db.table_exists("nonexistent") is True
