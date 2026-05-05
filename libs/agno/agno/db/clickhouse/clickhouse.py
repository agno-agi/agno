"""ClickHouse traces database adapter.

This adapter is intentionally **traces-only**. ClickHouse is a columnar OLAP
store that excels at high-volume append workloads (traces, events, metrics)
and at fast aggregate scans, but it does not provide row-level updates or
transactional guarantees suitable for sessions, memories, knowledge content,
or component configs. Pair this DB with a row-store (e.g. ``PostgresDb``) for
those concerns and use ``ClickhouseDb`` exclusively for tracing.

Typical usage::

    from agno.db.postgres import PostgresDb
    from agno.db.clickhouse import ClickhouseDb
    from agno.tracing import setup_tracing

    primary_db = PostgresDb(db_url="postgresql+psycopg://...")
    traces_db = ClickhouseDb(host="localhost", port=8123, database="agno_traces")

    setup_tracing(db=traces_db, batch_processing=True)
"""

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.db.base import BaseDb, ComponentType
from agno.db.clickhouse.schemas import SPANS_DDL, TRACES_DDL, VERSIONS_DDL
from agno.db.clickhouse.utils import (
    named_rows,
    row_to_span,
    row_to_trace,
    span_columns,
    span_to_row,
    trace_columns,
    trace_to_row,
)
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.knowledge import KnowledgeRow
from agno.utils.log import log_debug, log_error
from agno.utils.string import generate_id

if TYPE_CHECKING:
    from clickhouse_connect.driver.client import Client

    from agno.tracing.schemas import Span, Trace

try:
    import clickhouse_connect
except ImportError as e:
    raise ImportError(
        "`clickhouse-connect` not installed. Install with `pip install clickhouse-connect` "
        "or `pip install 'agno[clickhouse]'`."
    ) from e


_TRACES_ONLY_ERROR = (
    "ClickhouseDb is a traces-only adapter. Use a row-store (e.g. PostgresDb) "
    "for sessions, memories, knowledge, evals, and components."
)


class ClickhouseDb(BaseDb):
    """ClickHouse-backed database adapter for traces and spans only."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = "agno",
        secure: bool = False,
        client: Optional["Client"] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        id: Optional[str] = None,
        create_schema: bool = True,
    ):
        """
        Args:
            host: ClickHouse server host.
            port: HTTP port (8123 plain, 8443 TLS).
            username: ClickHouse username.
            password: ClickHouse password.
            database: ClickHouse database name. Created at startup if missing.
            secure: Use HTTPS when True.
            client: Pre-built ``clickhouse_connect`` client. When provided the
                connection arguments above are ignored.
            traces_table: Override for the traces table name.
            spans_table: Override for the spans table name.
            versions_table: Override for the schema-versions table name.
            id: Stable identifier for this DB instance. If omitted, a deterministic
                id is derived from the connection params so the same logical DB
                gets the same id across reloads.
            create_schema: Create database + tables on startup if missing.
        """
        if id is None:
            seed = f"clickhouse://{username}@{host}:{port}/{database}"
            id = generate_id(seed)
        super().__init__(
            id=id,
            traces_table=traces_table,
            spans_table=spans_table,
            versions_table=versions_table,
        )

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database = database
        self.secure = secure

        self._client_instance: Optional["Client"] = client
        self._create_schema = create_schema
        # Per-table cache of "have we already issued CREATE IF NOT EXISTS for
        # this table on this instance?" Mirrors the Postgres/Mongo adapters.
        # Each table is created lazily on first write through `_get_table`.
        self._table_cache: Dict[str, str] = {}
        self._database_ready = False

    # ------------------------------------------------------------------ schema

    @property
    def _client(self) -> "Client":
        """Lazily build the underlying clickhouse-connect client.

        We defer connecting until first use so the DB can be constructed in
        environments where the server isn't reachable yet (e.g. tests, app
        startup before docker-compose is healthy). The first real DB call will
        surface the connection error.
        """
        if self._client_instance is None:
            self._client_instance = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                secure=self.secure,
            )
        return self._client_instance

    def _get_table(self, table_type: str, create_table_if_not_found: bool = False) -> Optional[str]:
        """Resolve the qualified ``database.table`` name, creating it if asked.

        Mirrors the ``_get_table`` / ``_get_collection`` pattern used by the
        Postgres and Mongo adapters: write paths pass
        ``create_table_if_not_found=True``, read paths pass ``False`` so that
        reads against an empty DB return ``None`` instead of provisioning
        tables.

        First-time creates are server-idempotent (``CREATE TABLE IF NOT
        EXISTS``); the per-instance cache just avoids re-issuing the DDL.
        """
        if table_type in self._table_cache:
            return self._table_cache[table_type]

        ddl_map = {
            "traces": (TRACES_DDL, self.trace_table_name),
            "spans": (SPANS_DDL, self.span_table_name),
            "versions": (VERSIONS_DDL, self.versions_table_name),
        }
        if table_type not in ddl_map:
            return None
        ddl, name = ddl_map[table_type]

        if not create_table_if_not_found:
            # Read path: don't create. Return the qualified name only if the
            # table already exists on the server.
            if self.table_exists(name):
                qualified = f"{self.database}.{name}"
                self._table_cache[table_type] = qualified
                return qualified
            log_debug(f"ClickHouse table '{self.database}.{name}' not found")
            return None

        # Write path: create database + table if missing, then cache.
        if not self._create_schema:
            qualified = f"{self.database}.{name}"
            self._table_cache[table_type] = qualified
            return qualified
        try:
            if not self._database_ready:
                self._client.command(f"CREATE DATABASE IF NOT EXISTS {self.database}")
                self._database_ready = True
            already_existed = self.table_exists(name)
            self._client.command(ddl.format(db=self.database, table=name))
            qualified = f"{self.database}.{name}"
            self._table_cache[table_type] = qualified
            if already_existed:
                log_debug(f"ClickHouse table '{qualified}' already exists, skipping creation")
            else:
                log_debug(f"Successfully created ClickHouse table '{qualified}'")
            return qualified
        except Exception as e:
            log_error(f"Failed to ensure ClickHouse table '{name}': {e}")
            raise

    def close(self) -> None:
        if self._client_instance is not None:
            try:
                self._client_instance.close()
            except Exception:
                pass

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "type": "clickhouse",
                "host": self.host,
                "port": self.port,
                "database": self.database,
                "secure": self.secure,
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClickhouseDb":
        return cls(
            host=data.get("host", "localhost"),
            port=data.get("port", 8123),
            username=data.get("username", "default"),
            password=data.get("password", ""),
            database=data.get("database", "agno"),
            secure=data.get("secure", False),
            traces_table=data.get("traces_table"),
            spans_table=data.get("spans_table"),
            versions_table=data.get("versions_table"),
            id=data.get("id"),
        )

    # ------------------------------------------------------ required overrides

    def table_exists(self, table_name: str) -> bool:
        try:
            row = self._client.query(
                "SELECT count() FROM system.tables WHERE database = %(db)s AND name = %(t)s",
                parameters={"db": self.database, "t": table_name},
            )
            return bool(row.result_rows and row.result_rows[0][0])
        except Exception as e:
            log_error(f"table_exists check failed for {table_name}: {e}")
            return False

    def get_latest_schema_version(self, table_name: str) -> Optional[str]:
        try:
            qualified = self._get_table("versions")
            if qualified is None:
                return None
            res = self._client.query(
                f"SELECT version FROM {qualified} FINAL WHERE table_name = %(t)s LIMIT 1",
                parameters={"t": table_name},
            )
            if res.result_rows:
                return res.result_rows[0][0]
        except Exception as e:
            log_debug(f"get_latest_schema_version failed: {e}")
        return None

    def upsert_schema_version(self, table_name: str, version: str) -> None:
        now = datetime.now(timezone.utc)
        try:
            if self._get_table("versions", create_table_if_not_found=True) is None:
                return
            self._client.insert(
                table=self.versions_table_name,
                data=[(table_name, version, now, now)],
                column_names=["table_name", "version", "created_at", "updated_at"],
                database=self.database,
            )
        except Exception as e:
            log_error(f"upsert_schema_version failed: {e}")

    # ---------------------------------------------------------------- traces

    def upsert_trace(self, trace: "Trace") -> None:
        """Insert (or replace via ReplacingMergeTree) a trace row.

        ``ReplacingMergeTree`` deduplicates rows with the same sort key
        (``start_time, trace_id``) at merge time, keeping the row with the
        highest ``version`` value. We compute ``version`` server-side via the
        column DEFAULT, so the latest insert always wins.
        """
        try:
            if self._get_table("traces", create_table_if_not_found=True) is None:
                return
            self._client.insert(
                table=self.trace_table_name,
                data=[trace_to_row(trace)],
                column_names=trace_columns(),
                database=self.database,
            )
        except Exception as e:
            # Tracing must never break the host application.
            log_error(f"ClickhouseDb.upsert_trace failed: {e}")

    def get_trace(
        self,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        try:
            qualified = self._get_table("traces")
            if qualified is None:
                return None
            cols = ", ".join(trace_columns())
            where: List[str] = []
            params: Dict[str, Any] = {}
            if trace_id:
                where.append("trace_id = %(trace_id)s")
                params["trace_id"] = trace_id
            elif run_id:
                where.append("run_id = %(run_id)s")
                params["run_id"] = run_id
            elif session_id:
                where.append("session_id = %(session_id)s")
                params["session_id"] = session_id
            elif user_id:
                where.append("user_id = %(user_id)s")
                params["user_id"] = user_id
            elif agent_id:
                where.append("agent_id = %(agent_id)s")
                params["agent_id"] = agent_id
            else:
                log_debug("get_trace called without filters")
                return None

            sql = (
                f"SELECT {cols} FROM {qualified} FINAL "
                f"WHERE {' AND '.join(where)} ORDER BY start_time DESC LIMIT 1"
            )
            res = self._client.query(sql, parameters=params)
            if not res.result_rows:
                return None

            row = dict(zip(res.column_names, res.result_rows[0]))
            counts = self._span_counts_for([row["trace_id"]])
            total_spans, error_count = counts.get(row["trace_id"], (0, 0))
            return row_to_trace(row, total_spans=total_spans, error_count=error_count)
        except Exception as e:
            log_error(f"ClickhouseDb.get_trace failed: {e}")
            return None

    def get_traces(
        self,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
        filter_expr: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List, int]:
        try:
            qualified = self._get_table("traces")
            if qualified is None:
                return [], 0
            cols = ", ".join(trace_columns())
            where: List[str] = []
            params: Dict[str, Any] = {}
            for col, val in (
                ("run_id", run_id),
                ("session_id", session_id),
                ("user_id", user_id),
                ("agent_id", agent_id),
                ("team_id", team_id),
                ("workflow_id", workflow_id),
                ("status", status),
            ):
                if val is not None:
                    where.append(f"{col} = %({col})s")
                    params[col] = val
            if start_time is not None:
                where.append("start_time >= %(__start_time)s")
                params["__start_time"] = start_time
            if end_time is not None:
                where.append("end_time <= %(__end_time)s")
                params["__end_time"] = end_time

            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            limit_n = max(1, int(limit or 20))
            offset_n = max(0, ((int(page or 1)) - 1) * limit_n)

            count_sql = f"SELECT count() FROM {qualified} FINAL {where_sql}"
            total = int(self._client.query(count_sql, parameters=params).result_rows[0][0])

            page_sql = (
                f"SELECT {cols} FROM {qualified} FINAL "
                f"{where_sql} ORDER BY start_time DESC LIMIT {limit_n} OFFSET {offset_n}"
            )
            res = self._client.query(page_sql, parameters=params)
            rows = named_rows(res.column_names, res.result_rows)
            counts = self._span_counts_for([r["trace_id"] for r in rows])
            traces = [
                row_to_trace(
                    r,
                    total_spans=counts.get(r["trace_id"], (0, 0))[0],
                    error_count=counts.get(r["trace_id"], (0, 0))[1],
                )
                for r in rows
            ]
            return traces, total
        except Exception as e:
            log_error(f"ClickhouseDb.get_traces failed: {e}")
            return [], 0

    def get_trace_stats(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
        filter_expr: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            qualified = self._get_table("traces")
            if qualified is None:
                return [], 0
            where = ["t.session_id IS NOT NULL"]
            params: Dict[str, Any] = {}
            for col, val in (
                ("user_id", user_id),
                ("agent_id", agent_id),
                ("team_id", team_id),
                ("workflow_id", workflow_id),
            ):
                if val is not None:
                    where.append(f"t.{col} = %({col})s")
                    params[col] = val
            if start_time is not None:
                where.append("t.created_at >= %(__start_time)s")
                params["__start_time"] = start_time
            if end_time is not None:
                where.append("t.created_at <= %(__end_time)s")
                params["__end_time"] = end_time

            where_sql = " AND ".join(where)
            limit_n = max(1, int(limit or 20))
            offset_n = max(0, ((int(page or 1)) - 1) * limit_n)

            base_from = f"(SELECT * FROM {qualified} FINAL) AS t"

            count_sql = f"SELECT count(DISTINCT t.session_id) FROM {base_from} WHERE {where_sql}"
            total = int(self._client.query(count_sql, parameters=params).result_rows[0][0])

            page_sql = (
                f"SELECT t.session_id AS session_id, "
                f"any(t.user_id) AS user_id, any(t.agent_id) AS agent_id, "
                f"any(t.team_id) AS team_id, any(t.workflow_id) AS workflow_id, "
                f"count(DISTINCT t.trace_id) AS total_traces, "
                f"min(t.created_at) AS first_trace_at, max(t.created_at) AS last_trace_at "
                f"FROM {base_from} WHERE {where_sql} "
                f"GROUP BY t.session_id ORDER BY last_trace_at DESC "
                f"LIMIT {limit_n} OFFSET {offset_n}"
            )
            res = self._client.query(page_sql, parameters=params)
            stats: List[Dict[str, Any]] = []
            for row in res.result_rows:
                stats.append(dict(zip(res.column_names, row)))
            return stats, total
        except Exception as e:
            log_error(f"ClickhouseDb.get_trace_stats failed: {e}")
            return [], 0

    # ----------------------------------------------------------------- spans

    def create_span(self, span: "Span") -> None:
        try:
            if self._get_table("spans", create_table_if_not_found=True) is None:
                return
            self._client.insert(
                table=self.span_table_name,
                data=[span_to_row(span)],
                column_names=span_columns(),
                database=self.database,
            )
        except Exception as e:
            log_error(f"ClickhouseDb.create_span failed: {e}")

    def create_spans(self, spans: List) -> None:
        if not spans:
            return
        try:
            if self._get_table("spans", create_table_if_not_found=True) is None:
                return
            self._client.insert(
                table=self.span_table_name,
                data=[span_to_row(s) for s in spans],
                column_names=span_columns(),
                database=self.database,
            )
        except Exception as e:
            log_error(f"ClickhouseDb.create_spans failed: {e}")

    def get_span(self, span_id: str):
        try:
            qualified = self._get_table("spans")
            if qualified is None:
                return None
            cols = ", ".join(span_columns())
            res = self._client.query(
                f"SELECT {cols} FROM {qualified} WHERE span_id = %(span_id)s LIMIT 1",
                parameters={"span_id": span_id},
            )
            if not res.result_rows:
                return None
            return row_to_span(dict(zip(res.column_names, res.result_rows[0])))
        except Exception as e:
            log_error(f"ClickhouseDb.get_span failed: {e}")
            return None

    def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        try:
            qualified = self._get_table("spans")
            if qualified is None:
                return []
            cols = ", ".join(span_columns())
            where: List[str] = []
            params: Dict[str, Any] = {}
            if trace_id:
                where.append("trace_id = %(trace_id)s")
                params["trace_id"] = trace_id
            if parent_span_id:
                where.append("parent_span_id = %(parent_span_id)s")
                params["parent_span_id"] = parent_span_id

            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            limit_n = max(1, int(limit or 1000))
            sql = f"SELECT {cols} FROM {qualified} {where_sql} ORDER BY start_time ASC LIMIT {limit_n}"
            res = self._client.query(sql, parameters=params)
            return [row_to_span(dict(zip(res.column_names, r))) for r in res.result_rows]
        except Exception as e:
            log_error(f"ClickhouseDb.get_spans failed: {e}")
            return []

    # ------------------------------------------------------- internal helpers

    def _span_counts_for(self, trace_ids: List[str]) -> Dict[str, Tuple[int, int]]:
        """Compute (total_spans, error_count) per trace_id in a single query.

        Trace rows in ClickHouse don't store these aggregates — they're derived
        from the spans table at read time, mirroring how the Postgres adapter
        joins for the same numbers.
        """
        if not trace_ids:
            return {}
        try:
            qualified = self._get_table("spans")
            if qualified is None:
                return {}
            res = self._client.query(
                f"SELECT trace_id, count() AS total, "
                f"sumIf(1, status_code = 'ERROR') AS errors "
                f"FROM {qualified} "
                f"WHERE trace_id IN %(ids)s GROUP BY trace_id",
                parameters={"ids": trace_ids},
            )
            return {r[0]: (int(r[1]), int(r[2])) for r in res.result_rows}
        except Exception as e:
            log_debug(f"_span_counts_for failed: {e}")
            return {}

    # ----------------------------- traces-only behaviour for non-trace methods
    #
    # ClickHouse is an OLAP store and isn't a sensible target for sessions,
    # memories, knowledge, evals, or component configs. We split behaviour:
    #
    # * Read-side methods return empty results so this DB can be passed to
    #   ``AgentOS(db=...)`` alongside ``setup_tracing`` without spamming
    #   ``Error loading Agents/Teams/Workflows from database`` on startup
    # * Write-side methods still raise ``NotImplementedError`` so accidental
    #   storage attempts are loud rather than silently dropped.

    # --- Sessions ---
    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def get_session(self, *args, **kwargs):  # type: ignore[override]
        return None

    def get_sessions(self, *args, **kwargs):  # type: ignore[override]
        deserialize = kwargs.get("deserialize", True)
        return [] if deserialize else ([], 0)

    def rename_session(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def upsert_session(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def upsert_sessions(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Memory ---
    def clear_memories(self) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        return []

    def get_user_memory(self, *args, **kwargs):  # type: ignore[override]
        return None

    def get_user_memories(self, *args, **kwargs):  # type: ignore[override]
        deserialize = kwargs.get("deserialize", True)
        return [] if deserialize else ([], 0)

    def get_user_memory_stats(self, *args, **kwargs):  # type: ignore[override]
        return [], 0

    def upsert_user_memory(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def upsert_memories(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Metrics ---
    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        return [], None

    def calculate_metrics(self) -> Optional[Any]:
        return None

    # --- Knowledge ---
    def delete_knowledge_content(self, id: str):
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        return None

    def get_knowledge_contents(self, *args, **kwargs):  # type: ignore[override]
        return [], 0

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Evals ---
    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def get_eval_run(self, *args, **kwargs):  # type: ignore[override]
        return None

    def get_eval_runs(self, *args, **kwargs):  # type: ignore[override]
        deserialize = kwargs.get("deserialize", True)
        return [] if deserialize else ([], 0)

    def rename_eval_run(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Cultural Knowledge ---
    def clear_cultural_knowledge(self) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def delete_cultural_knowledge(self, id: str) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def get_cultural_knowledge(self, id: str) -> Optional[CulturalKnowledge]:
        return None

    def get_all_cultural_knowledge(self, *args, **kwargs):  # type: ignore[override]
        return []

    def upsert_cultural_knowledge(self, cultural_knowledge: CulturalKnowledge) -> Optional[CulturalKnowledge]:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Learnings ---
    def get_learning(self, *args, **kwargs):  # type: ignore[override]
        return None

    def upsert_learning(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    def get_learnings(self, *args, **kwargs):  # type: ignore[override]
        return []

    # --- Components (called by AgentOS at startup) ---
    def get_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
    ) -> Optional[Dict[str, Any]]:
        return None

    def list_components(self, *args, **kwargs):  # type: ignore[override]
        return [], 0

    def get_config(self, *args, **kwargs):  # type: ignore[override]
        return None

    def list_configs(self, *args, **kwargs):  # type: ignore[override]
        return []

    def get_links(self, *args, **kwargs):  # type: ignore[override]
        return []

    def get_dependents(self, *args, **kwargs):  # type: ignore[override]
        return []

    def load_component_graph(self, *args, **kwargs):  # type: ignore[override]
        return None
