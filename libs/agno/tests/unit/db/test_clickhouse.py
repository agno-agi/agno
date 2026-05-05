"""Unit tests for ClickhouseDb / AsyncClickhouseDb.

These tests don't touch a real ClickHouse server — the underlying client is
mocked. They cover the contract that other tests would otherwise have to
boot a container to verify:

- Deterministic ``id`` derived from connection params (matches PostgresDb).
- ``to_dict`` / ``from_dict`` round-trip preserves all fields.
- Traces-only behaviour: writes for sessions/memory/etc. raise; reads return
  empty results so ``AgentOS(db=traces_db)`` works without errors.
- ``_get_table`` cache logic — first write creates and caches; subsequent
  writes hit the cache and skip DDL.

For end-to-end behaviour against a live server, see
``libs/agno/tests/integration/db/clickhouse``.
"""

from datetime import datetime, timezone
from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

from agno.db.clickhouse import AsyncClickhouseDb, ClickhouseDb


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _mock_client(rows: Optional[List[Any]] = None, columns: Optional[List[str]] = None) -> MagicMock:
    """Build a minimal stand-in for a clickhouse-connect Client."""
    client = MagicMock()
    query_result = MagicMock()
    query_result.result_rows = rows or []
    query_result.column_names = columns or []
    client.query.return_value = query_result
    return client


def _make_db(client: Optional[MagicMock] = None) -> ClickhouseDb:
    """Construct a ClickhouseDb with an injected mock client (no real connection)."""
    return ClickhouseDb(
        host="localhost",
        port=8123,
        username="ai",
        password="ai",
        database="agno_test",
        client=client or _mock_client(),
        # create_schema is True by default but creation is gated per-table now,
        # so the constructor doesn't issue any DDL.
    )


# --------------------------------------------------------------------------- #
# Deterministic id
# --------------------------------------------------------------------------- #


class TestDeterministicId:
    def test_sync_id_is_stable_across_constructions(self):
        a = ClickhouseDb(host="h", port=1, username="u", password="p", database="d", create_schema=False)
        b = ClickhouseDb(host="h", port=1, username="u", password="p", database="d", create_schema=False)
        assert a.id == b.id

    def test_sync_id_changes_with_connection_params(self):
        a = ClickhouseDb(host="h1", port=1, username="u", password="p", database="d", create_schema=False)
        b = ClickhouseDb(host="h2", port=1, username="u", password="p", database="d", create_schema=False)
        assert a.id != b.id

    def test_sync_explicit_id_wins(self):
        db = ClickhouseDb(
            host="h", port=1, username="u", password="p", database="d", id="traces", create_schema=False
        )
        assert db.id == "traces"

    def test_sync_and_async_have_distinct_default_ids_for_same_connection(self):
        # The seed is namespaced by adapter so a sync and async DB pointing at
        # the same server don't collide in AgentOS's registry.
        sync = ClickhouseDb(host="h", port=1, username="u", password="p", database="d", create_schema=False)
        async_ = AsyncClickhouseDb(
            host="h", port=1, username="u", password="p", database="d", create_schema=False
        )
        assert sync.id != async_.id

    def test_async_id_is_stable_across_constructions(self):
        a = AsyncClickhouseDb(
            host="h", port=1, username="u", password="p", database="d", create_schema=False
        )
        b = AsyncClickhouseDb(
            host="h", port=1, username="u", password="p", database="d", create_schema=False
        )
        assert a.id == b.id


# --------------------------------------------------------------------------- #
# to_dict / from_dict round-trip
# --------------------------------------------------------------------------- #


class TestRoundTrip:
    def test_all_fields_survive_roundtrip(self):
        original = ClickhouseDb(
            host="h",
            port=8443,
            username="u",
            password="p",
            database="d",
            secure=True,
            traces_table="t",
            spans_table="sp",
            versions_table="v",
            id="my-traces",
            create_schema=False,
        )
        restored = ClickhouseDb.from_dict(original.to_dict())

        assert restored.host == "h"
        assert restored.port == 8443
        assert restored.database == "d"
        assert restored.secure is True
        assert restored.trace_table_name == "t"
        assert restored.span_table_name == "sp"
        assert restored.versions_table_name == "v"
        assert restored.id == "my-traces"

    def test_to_dict_includes_type_marker(self):
        db = ClickhouseDb(
            host="h", port=1, username="u", password="p", database="d", create_schema=False
        )
        assert db.to_dict()["type"] == "clickhouse"


# --------------------------------------------------------------------------- #
# Traces-only contract
# --------------------------------------------------------------------------- #


class TestTracesOnlyContract:
    """ClickhouseDb supports trace persistence and nothing else.

    Read methods return empty results so ``AgentOS(db=traces_db)`` doesn't
    spam errors at startup; write methods raise so accidental misuse is loud.
    """

    @pytest.fixture
    def db(self) -> ClickhouseDb:
        return _make_db()

    # ----- writes raise --------------------------------------------------- #

    @pytest.mark.parametrize(
        "method,args",
        [
            ("delete_session", ("sid",)),
            ("rename_session", ("sid", None, "name")),
            ("upsert_session", (object(),)),
            ("delete_user_memory", ("mid",)),
            ("upsert_user_memory", (object(),)),
            ("delete_knowledge_content", ("kid",)),
            ("upsert_knowledge_content", (object(),)),
            ("create_eval_run", (object(),)),
            ("delete_eval_runs", (["rid"],)),
            ("upsert_cultural_knowledge", (object(),)),
            ("upsert_learning", ("id", "type", {})),
            ("delete_learning", ("id",)),
        ],
    )
    def test_write_methods_raise(self, db: ClickhouseDb, method: str, args: tuple):
        with pytest.raises(NotImplementedError, match="traces-only"):
            getattr(db, method)(*args)

    # ----- reads return empty -------------------------------------------- #

    def test_get_session_returns_none(self, db: ClickhouseDb):
        assert db.get_session("sid") is None

    def test_get_sessions_returns_empty_list_or_tuple(self, db: ClickhouseDb):
        assert db.get_sessions() == []
        assert db.get_sessions(deserialize=False) == ([], 0)

    def test_get_user_memories_returns_empty(self, db: ClickhouseDb):
        assert db.get_user_memories() == []
        assert db.get_user_memories(deserialize=False) == ([], 0)

    def test_get_metrics_returns_empty(self, db: ClickhouseDb):
        assert db.get_metrics() == ([], None)

    def test_list_components_returns_empty(self, db: ClickhouseDb):
        # AgentOS calls this at startup; must not raise.
        assert db.list_components() == ([], 0)
        assert db.get_config(component_id="missing") is None
        assert db.get_component(component_id="missing") is None

    def test_get_eval_runs_returns_empty(self, db: ClickhouseDb):
        assert db.get_eval_runs() == []
        assert db.get_eval_runs(deserialize=False) == ([], 0)


# --------------------------------------------------------------------------- #
# _get_table cache behaviour
# --------------------------------------------------------------------------- #


class TestGetTableCache:
    def test_first_write_creates_and_caches(self):
        client = _mock_client()
        # `table_exists` issues a `SELECT count() FROM system.tables` query —
        # return 0 the first time so _get_table treats the table as new.
        not_found = MagicMock(result_rows=[(0,)], column_names=["count()"])
        client.query.return_value = not_found

        db = _make_db(client)
        qualified = db._get_table("traces", create_table_if_not_found=True)

        assert qualified == "agno_test.agno_traces"
        # CREATE DATABASE + CREATE TABLE → 2 .command() calls.
        assert client.command.call_count == 2
        # Cached after the first hit.
        client.command.reset_mock()
        again = db._get_table("traces", create_table_if_not_found=True)
        assert again == qualified
        assert client.command.call_count == 0  # cache hit, no DDL

    def test_read_path_returns_none_when_table_missing(self):
        client = _mock_client()
        not_found = MagicMock(result_rows=[(0,)], column_names=["count()"])
        client.query.return_value = not_found

        db = _make_db(client)
        # No create_table_if_not_found → just probes via table_exists.
        assert db._get_table("traces") is None
        # No DDL was issued.
        assert client.command.call_count == 0

    def test_read_path_returns_qualified_when_table_exists(self):
        client = _mock_client()
        exists = MagicMock(result_rows=[(1,)], column_names=["count()"])
        client.query.return_value = exists

        db = _make_db(client)
        assert db._get_table("traces") == "agno_test.agno_traces"


# --------------------------------------------------------------------------- #
# Trace round-trip via mocked client
# --------------------------------------------------------------------------- #


class TestFilterExprConverter:
    """Unit-test the FilterExpr -> ClickHouse SQL fragment converter directly."""

    @pytest.fixture
    def cols(self):
        from agno.db.filter_converter import TRACE_COLUMNS

        return TRACE_COLUMNS

    def test_eq_emits_parameterized_sql(self, cols):
        from agno.db.clickhouse.utils import filter_expr_to_clickhouse

        params: dict = {}
        sql = filter_expr_to_clickhouse(
            {"op": "EQ", "key": "trace_id", "value": "abc"}, params, cols
        )
        assert "trace_id =" in sql
        # Value is parameterized, not interpolated.
        assert "abc" not in sql
        assert "abc" in params.values()

    def test_and_or_not_compose(self, cols):
        from agno.db.clickhouse.utils import filter_expr_to_clickhouse

        params: dict = {}
        sql = filter_expr_to_clickhouse(
            {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {
                        "op": "OR",
                        "conditions": [
                            {"op": "EQ", "key": "agent_id", "value": "a1"},
                            {"op": "NOT", "condition": {"op": "EQ", "key": "user_id", "value": "u1"}},
                        ],
                    },
                ],
            },
            params,
            cols,
        )
        assert " AND " in sql
        assert " OR " in sql
        assert "NOT (" in sql
        # 3 leaf comparisons → 3 placeholders.
        assert len(params) == 3

    def test_in_uses_list_placeholder(self, cols):
        from agno.db.clickhouse.utils import filter_expr_to_clickhouse

        params: dict = {}
        sql = filter_expr_to_clickhouse(
            {"op": "IN", "key": "status", "values": ["OK", "ERROR"]}, params, cols
        )
        assert " IN " in sql
        assert ["OK", "ERROR"] in params.values()

    def test_unknown_column_raises(self, cols):
        from agno.db.clickhouse.utils import filter_expr_to_clickhouse

        with pytest.raises(ValueError, match="Invalid filter field"):
            filter_expr_to_clickhouse(
                {"op": "EQ", "key": "not_a_column", "value": "x"}, {}, cols
            )

    def test_column_alias_is_prefixed(self, cols):
        from agno.db.clickhouse.utils import filter_expr_to_clickhouse

        params: dict = {}
        sql = filter_expr_to_clickhouse(
            {"op": "EQ", "key": "agent_id", "value": "a1"}, params, cols, column_alias="t"
        )
        assert sql.startswith("t.agent_id ")

    def test_max_depth_enforced(self, cols):
        from agno.db.clickhouse.utils import filter_expr_to_clickhouse

        # Build a 12-deep AND chain (limit is 10).
        node = {"op": "EQ", "key": "trace_id", "value": "x"}
        for _ in range(12):
            node = {"op": "AND", "conditions": [node]}
        with pytest.raises(ValueError, match="maximum nesting depth"):
            filter_expr_to_clickhouse(node, {}, cols)

    def test_datetime_columns_coerce_iso_strings_to_utc(self, cols):
        """Filter values for start_time/end_time/created_at must be parsed to
        tz-aware datetimes so ClickHouse's DateTime64('UTC') accepts them."""
        from datetime import datetime, timezone

        from agno.db.clickhouse.utils import filter_expr_to_clickhouse

        params: dict = {}
        filter_expr_to_clickhouse(
            {"op": "GTE", "key": "start_time", "value": "2026-05-05T16:30:00+05:30"},
            params,
            cols,
        )
        bound = next(iter(params.values()))
        assert isinstance(bound, datetime)
        assert bound.tzinfo is not None
        assert bound.utcoffset() == timezone.utc.utcoffset(bound)  # converted to UTC

    def test_in_filter_with_datetime_column_coerces_each_value(self, cols):
        from datetime import datetime

        from agno.db.clickhouse.utils import filter_expr_to_clickhouse

        params: dict = {}
        filter_expr_to_clickhouse(
            {
                "op": "IN",
                "key": "created_at",
                "values": ["2026-05-05T10:00:00Z", "2026-05-05T11:00:00+05:30"],
            },
            params,
            cols,
        )
        bound = next(iter(params.values()))
        assert isinstance(bound, list)
        assert all(isinstance(v, datetime) for v in bound)


class TestTraceWritePath:
    """Verify upsert_trace + create_spans hit the right insert API.

    A live-server end-to-end test lives in tests/integration/db/clickhouse.
    This unit test only checks that we form the call correctly.
    """

    def test_upsert_trace_calls_insert_with_expected_args(self):
        from agno.tracing.schemas import Trace

        client = _mock_client()
        # Make the table-existence probe say "exists".
        client.query.return_value = MagicMock(result_rows=[(1,)], column_names=["count()"])
        db = _make_db(client)

        now = datetime.now(timezone.utc)
        trace = Trace(
            trace_id="t-1",
            name="run",
            status="OK",
            start_time=now,
            end_time=now,
            duration_ms=42,
            total_spans=1,
            error_count=0,
            run_id="r-1",
            session_id="s-1",
            user_id=None,
            agent_id="agent-1",
            team_id=None,
            workflow_id=None,
            created_at=now,
        )
        db.upsert_trace(trace)

        client.insert.assert_called_once()
        kwargs = client.insert.call_args.kwargs
        assert kwargs["table"] == db.trace_table_name
        assert kwargs["database"] == db.database
        assert "trace_id" in kwargs["column_names"]
        # Single row, with the trace_id we passed in.
        assert kwargs["data"][0][0] == "t-1"
