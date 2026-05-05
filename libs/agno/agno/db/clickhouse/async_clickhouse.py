"""Async ClickHouse traces database adapter.

Mirrors :class:`~agno.db.clickhouse.clickhouse.ClickhouseDb` against
``clickhouse_connect.get_async_client``. Use this when your application is
fully async — ``setup_tracing`` will detect ``AsyncBaseDb`` and ``await`` the
exporter calls automatically.
"""

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.db.base import AsyncBaseDb
from agno.db.clickhouse.schemas import SPANS_DDL, TRACES_DDL, VERSIONS_DDL
from agno.db.clickhouse.utils import (
    coerce_datetime,
    filter_expr_to_clickhouse,
    named_rows,
    row_to_span,
    row_to_trace,
    span_columns,
    span_to_row,
    trace_columns,
    trace_to_row,
)
from agno.db.filter_converter import TRACE_COLUMNS as TRACE_FILTER_COLUMNS
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.knowledge import KnowledgeRow
from agno.utils.log import log_debug, log_error
from agno.utils.string import generate_id

if TYPE_CHECKING:
    from clickhouse_connect.driver.asyncclient import AsyncClient

    from agno.tracing.schemas import Span, Trace

try:
    import clickhouse_connect
except ImportError as e:
    raise ImportError(
        "`clickhouse-connect` not installed. Install with `pip install clickhouse-connect` "
        "or `pip install 'agno[clickhouse]'`."
    ) from e


_TRACES_ONLY_ERROR = (
    "AsyncClickhouseDb is a traces-only adapter. Use a row-store (e.g. PostgresDb) "
    "for sessions, memories, knowledge, evals, and components."
)


class AsyncClickhouseDb(AsyncBaseDb):
    """Async ClickHouse-backed database adapter for traces and spans only."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = "agno",
        secure: bool = False,
        async_client: Optional["AsyncClient"] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        id: Optional[str] = None,
        create_schema: bool = True,
    ):
        if id is None:
            seed = f"clickhouse-async://{username}@{host}:{port}/{database}"
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
        self._client: Optional["AsyncClient"] = async_client
        self._create_schema = create_schema
        # Per-table cache of "have we already issued CREATE IF NOT EXISTS for
        # this table on this instance?" Mirrors the Postgres/Mongo adapters.
        self._table_cache: Dict[str, str] = {}
        self._database_ready = False

    async def _client_(self) -> "AsyncClient":
        if self._client is None:
            self._client = await clickhouse_connect.get_async_client(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                secure=self.secure,
            )
        return self._client

    async def _get_table(self, table_type: str, create_table_if_not_found: bool = False) -> Optional[str]:
        """Resolve the qualified ``database.table`` name, creating it if asked.

        Async mirror of :meth:`ClickhouseDb._get_table`. See that method for
        the rationale; same write/read split applies here.
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
            if await self.table_exists(name):
                qualified = f"{self.database}.{name}"
                self._table_cache[table_type] = qualified
                return qualified
            log_debug(f"AsyncClickHouse table '{self.database}.{name}' not found")
            return None

        if not self._create_schema:
            qualified = f"{self.database}.{name}"
            self._table_cache[table_type] = qualified
            return qualified
        try:
            client = await self._client_()
            if not self._database_ready:
                await client.command(f"CREATE DATABASE IF NOT EXISTS {self.database}")
                self._database_ready = True
            already_existed = await self.table_exists(name)
            await client.command(ddl.format(db=self.database, table=name))
            qualified = f"{self.database}.{name}"
            self._table_cache[table_type] = qualified
            if already_existed:
                log_debug(f"AsyncClickHouse table '{qualified}' already exists, skipping creation")
            else:
                log_debug(f"Successfully created AsyncClickHouse table '{qualified}'")
            return qualified
        except Exception as e:
            log_error(f"Failed to ensure AsyncClickHouse table '{name}': {e}")
            raise

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass

    # ------------------------------------------------------ required overrides

    async def table_exists(self, table_name: str) -> bool:
        try:
            client = await self._client_()
            res = await client.query(
                "SELECT count() FROM system.tables WHERE database = %(db)s AND name = %(t)s",
                parameters={"db": self.database, "t": table_name},
            )
            return bool(res.result_rows and res.result_rows[0][0])
        except Exception as e:
            log_error(f"table_exists check failed: {e}")
            return False

    async def get_latest_schema_version(self, table_name: str) -> str:
        try:
            qualified = await self._get_table("versions")
            if qualified is None:
                return ""
            client = await self._client_()
            res = await client.query(
                f"SELECT version FROM {qualified} FINAL WHERE table_name = %(t)s LIMIT 1",
                parameters={"t": table_name},
            )
            if res.result_rows:
                return res.result_rows[0][0]
        except Exception as e:
            log_debug(f"get_latest_schema_version failed: {e}")
        return ""

    async def upsert_schema_version(self, table_name: str, version: str) -> None:
        now = datetime.now(timezone.utc)
        try:
            if await self._get_table("versions", create_table_if_not_found=True) is None:
                return
            client = await self._client_()
            await client.insert(
                table=self.versions_table_name,
                data=[(table_name, version, now, now)],
                column_names=["table_name", "version", "created_at", "updated_at"],
                database=self.database,
            )
        except Exception as e:
            log_error(f"upsert_schema_version failed: {e}")

    # ---------------------------------------------------------------- traces

    async def upsert_trace(self, trace: "Trace") -> None:
        try:
            if await self._get_table("traces", create_table_if_not_found=True) is None:
                return
            client = await self._client_()
            await client.insert(
                table=self.trace_table_name,
                data=[trace_to_row(trace)],
                column_names=trace_columns(),
                database=self.database,
            )
        except Exception as e:
            log_error(f"AsyncClickhouseDb.upsert_trace failed: {e}")

    async def get_trace(
        self,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        try:
            qualified = await self._get_table("traces")
            if qualified is None:
                return None
            client = await self._client_()
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
                return None

            sql = (
                f"SELECT {cols} FROM {qualified} FINAL "
                f"WHERE {' AND '.join(where)} ORDER BY start_time DESC LIMIT 1"
            )
            res = await client.query(sql, parameters=params)
            if not res.result_rows:
                return None

            row = dict(zip(res.column_names, res.result_rows[0]))
            counts = await self._span_counts_for([row["trace_id"]])
            total_spans, error_count = counts.get(row["trace_id"], (0, 0))
            return row_to_trace(row, total_spans=total_spans, error_count=error_count)
        except Exception as e:
            log_error(f"AsyncClickhouseDb.get_trace failed: {e}")
            return None

    async def get_traces(
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
            qualified = await self._get_table("traces")
            if qualified is None:
                return [], 0
            client = await self._client_()
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
                params["__start_time"] = coerce_datetime(start_time)
            if end_time is not None:
                where.append("end_time <= %(__end_time)s")
                params["__end_time"] = coerce_datetime(end_time)

            if filter_expr:
                try:
                    where.append(
                        filter_expr_to_clickhouse(filter_expr, params, allowed_columns=TRACE_FILTER_COLUMNS)
                    )
                except ValueError:
                    raise
                except (KeyError, TypeError) as e:
                    raise ValueError(f"Invalid filter expression: {e}") from e

            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            limit_n = max(1, int(limit or 20))
            offset_n = max(0, ((int(page or 1)) - 1) * limit_n)

            count_res = await client.query(
                f"SELECT count() FROM {qualified} FINAL {where_sql}",
                parameters=params,
            )
            total = int(count_res.result_rows[0][0])

            page_res = await client.query(
                f"SELECT {cols} FROM {qualified} FINAL "
                f"{where_sql} ORDER BY start_time DESC LIMIT {limit_n} OFFSET {offset_n}",
                parameters=params,
            )
            rows = named_rows(page_res.column_names, page_res.result_rows)
            counts = await self._span_counts_for([r["trace_id"] for r in rows])
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
            log_error(f"AsyncClickhouseDb.get_traces failed: {e}")
            return [], 0

    async def get_trace_stats(
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
            qualified = await self._get_table("traces")
            if qualified is None:
                return [], 0
            client = await self._client_()
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
                params["__start_time"] = coerce_datetime(start_time)
            if end_time is not None:
                where.append("t.created_at <= %(__end_time)s")
                params["__end_time"] = coerce_datetime(end_time)

            if filter_expr:
                try:
                    where.append(
                        filter_expr_to_clickhouse(
                            filter_expr, params, allowed_columns=TRACE_FILTER_COLUMNS, column_alias="t"
                        )
                    )
                except ValueError:
                    raise
                except (KeyError, TypeError) as e:
                    raise ValueError(f"Invalid filter expression: {e}") from e

            where_sql = " AND ".join(where)
            limit_n = max(1, int(limit or 20))
            offset_n = max(0, ((int(page or 1)) - 1) * limit_n)

            base_from = f"(SELECT * FROM {qualified} FINAL) AS t"

            count_res = await client.query(
                f"SELECT count(DISTINCT t.session_id) FROM {base_from} WHERE {where_sql}",
                parameters=params,
            )
            total = int(count_res.result_rows[0][0])

            page_res = await client.query(
                f"SELECT t.session_id AS session_id, "
                f"any(t.user_id) AS user_id, any(t.agent_id) AS agent_id, "
                f"any(t.team_id) AS team_id, any(t.workflow_id) AS workflow_id, "
                f"count(DISTINCT t.trace_id) AS total_traces, "
                f"min(t.created_at) AS first_trace_at, max(t.created_at) AS last_trace_at "
                f"FROM {base_from} WHERE {where_sql} "
                f"GROUP BY t.session_id ORDER BY last_trace_at DESC "
                f"LIMIT {limit_n} OFFSET {offset_n}",
                parameters=params,
            )
            return [dict(zip(page_res.column_names, row)) for row in page_res.result_rows], total
        except Exception as e:
            log_error(f"AsyncClickhouseDb.get_trace_stats failed: {e}")
            return [], 0

    # ----------------------------------------------------------------- spans

    async def create_span(self, span: "Span") -> None:
        try:
            if await self._get_table("spans", create_table_if_not_found=True) is None:
                return
            client = await self._client_()
            await client.insert(
                table=self.span_table_name,
                data=[span_to_row(span)],
                column_names=span_columns(),
                database=self.database,
            )
        except Exception as e:
            log_error(f"AsyncClickhouseDb.create_span failed: {e}")

    async def create_spans(self, spans: List) -> None:
        if not spans:
            return
        try:
            if await self._get_table("spans", create_table_if_not_found=True) is None:
                return
            client = await self._client_()
            await client.insert(
                table=self.span_table_name,
                data=[span_to_row(s) for s in spans],
                column_names=span_columns(),
                database=self.database,
            )
        except Exception as e:
            log_error(f"AsyncClickhouseDb.create_spans failed: {e}")

    async def get_span(self, span_id: str):
        try:
            qualified = await self._get_table("spans")
            if qualified is None:
                return None
            client = await self._client_()
            cols = ", ".join(span_columns())
            res = await client.query(
                f"SELECT {cols} FROM {qualified} WHERE span_id = %(span_id)s LIMIT 1",
                parameters={"span_id": span_id},
            )
            if not res.result_rows:
                return None
            return row_to_span(dict(zip(res.column_names, res.result_rows[0])))
        except Exception as e:
            log_error(f"AsyncClickhouseDb.get_span failed: {e}")
            return None

    async def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        try:
            qualified = await self._get_table("spans")
            if qualified is None:
                return []
            client = await self._client_()
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
            res = await client.query(
                f"SELECT {cols} FROM {qualified} {where_sql} ORDER BY start_time ASC LIMIT {limit_n}",
                parameters=params,
            )
            return [row_to_span(dict(zip(res.column_names, r))) for r in res.result_rows]
        except Exception as e:
            log_error(f"AsyncClickhouseDb.get_spans failed: {e}")
            return []

    async def _span_counts_for(self, trace_ids: List[str]) -> Dict[str, Tuple[int, int]]:
        if not trace_ids:
            return {}
        try:
            qualified = await self._get_table("spans")
            if qualified is None:
                return {}
            client = await self._client_()
            res = await client.query(
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
    # See ClickhouseDb for rationale: read methods return empty results so
    # this DB drops into ``AgentOS(db=...)`` without spurious load errors;
    # write methods raise to make accidental storage attempts loud.

    # --- Sessions ---
    async def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def get_session(self, *args, **kwargs):  # type: ignore[override]
        return None

    async def get_sessions(self, *args, **kwargs):  # type: ignore[override]
        deserialize = kwargs.get("deserialize", True)
        return [] if deserialize else ([], 0)

    async def rename_session(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def upsert_session(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Memory ---
    async def clear_memories(self) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        return []

    async def get_user_memory(self, *args, **kwargs):  # type: ignore[override]
        return None

    async def get_user_memories(self, *args, **kwargs):  # type: ignore[override]
        deserialize = kwargs.get("deserialize", True)
        return [] if deserialize else ([], 0)

    async def get_user_memory_stats(self, *args, **kwargs):  # type: ignore[override]
        return [], 0

    async def upsert_user_memory(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Metrics ---
    async def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        return [], None

    async def calculate_metrics(self) -> Optional[Any]:
        return None

    # --- Knowledge ---
    async def delete_knowledge_content(self, id: str):
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        return None

    async def get_knowledge_contents(self, *args, **kwargs):  # type: ignore[override]
        return [], 0

    async def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Evals ---
    async def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def get_eval_run(self, *args, **kwargs):  # type: ignore[override]
        return None

    async def get_eval_runs(self, *args, **kwargs):  # type: ignore[override]
        deserialize = kwargs.get("deserialize", True)
        return [] if deserialize else ([], 0)

    async def rename_eval_run(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Cultural Knowledge ---
    async def clear_cultural_knowledge(self) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def delete_cultural_knowledge(self, id: str) -> None:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def get_cultural_knowledge(self, *args, **kwargs):  # type: ignore[override]
        return None

    async def get_all_cultural_knowledge(self, *args, **kwargs):  # type: ignore[override]
        return []

    async def upsert_cultural_knowledge(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    # --- Learnings ---
    async def get_learning(self, *args, **kwargs):  # type: ignore[override]
        return None

    async def upsert_learning(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def delete_learning(self, id: str) -> bool:
        raise NotImplementedError(_TRACES_ONLY_ERROR)

    async def get_learnings(self, *args, **kwargs):  # type: ignore[override]
        return []
