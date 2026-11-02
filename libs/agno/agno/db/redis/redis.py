import json
import time
from datetime import date, datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Tuple, Union
from uuid import uuid4

from packaging import version as packaging_version

if TYPE_CHECKING:
    from agno.db.schemas.jobs import QueueWriteOutcome
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.redis.utils import (
    METRICS_SCAN_COUNT,
    apply_filters,
    apply_pagination,
    apply_sorting,
    build_component_metrics_legacy_runs,
    build_component_metrics_run,
    build_component_metrics_session,
    bulk_upsert_component_metrics,
    bulk_upsert_user_metrics_rows,
    create_index_entries,
    delete_component_metrics,
    delete_user_metrics_rows,
    deserialize_component_metrics_record,
    deserialize_data,
    deserialize_user_metrics_record,
    generate_created_at_index_key,
    generate_index_key,
    generate_metrics_prefix,
    generate_redis_key,
    get_all_keys_for_table,
    metrics_day_start,
    metrics_record_key,
    remove_index_entries,
    reopen_metrics_day,
    reopen_metrics_days_from,
    reopen_metrics_month,
    serialize_data,
    upsert_user_metrics_row,
    user_metrics_record_id,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import (
    COMPONENT_METRICS_KEY_COLUMNS,
    METRICS_BATCH_SIZE,
    METRICS_LOCK_SECONDS,
    METRICS_REFRESH_ID,
    METRICS_STOPPED_ERROR,
    USER_METRICS_COUNT_COLUMNS,
    add_metrics_month_totals,
    build_metrics_by_owner_from_rows,
    build_metrics_from_user_metrics,
    build_single_run_row,
    build_user_metrics_month_rows,
    build_user_metrics_rows,
    calculate_date_component_metrics,
    component_metrics_rows_to_write,
    database_error_message,
    deserialize_run,
    deserialize_session,
    deserialize_sessions,
    drop_legacy_metrics,
    filter_context_runs,
    get_metrics_fingerprint,
    get_metrics_reopen_session_ids,
    get_metrics_rows_by_key,
    get_months_to_calculate_metrics_for,
    list_metrics_totals_models,
    merge_metrics_totals,
    merge_runs_table_with_legacy_blob,
    metric_record_day,
    metrics_calculation_enabled,
    metrics_day_completed,
    metrics_day_to_reopen,
    metrics_days_since_last_calculation,
    metrics_full_months,
    metrics_month_end,
    metrics_nested_run_ids,
    metrics_refresh_status,
    metrics_remote_member_team_session_ids,
    metrics_versions,
    resolve_metrics_fields,
    total_metrics_rows,
    user_metrics_rows_to_write,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    from redis import Redis, RedisCluster
except ImportError:
    raise ImportError("`redis` not installed. Please install it using `pip install redis`")


class RedisDb(BaseDb):
    serializes_sessions: bool = True

    def __init__(
        self,
        id: Optional[str] = None,
        redis_client: Optional[Union[Redis, RedisCluster]] = None,
        db_url: Optional[str] = None,
        db_prefix: str = "agno",
        expire: Optional[int] = None,
        session_table: Optional[str] = None,
        runs_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        component_metrics_table: Optional[str] = None,
        user_metrics_table: Optional[str] = None,
        metrics_refreshes_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
    ):
        """
        Interface for interacting with a Redis database.

        The following order is used to determine the database connection:
            1. Use the redis_client if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        db_url only supports single-node Redis connections, if you need Redis Cluster support, provide a redis_client.

        Args:
            id (Optional[str]): The ID of the database.
            redis_client (Optional[Redis]): Redis client instance to use. If not provided a new client will be created.
            db_url (Optional[str]): Redis connection URL (e.g., "redis://localhost:6379/0" or "rediss://user:pass@host:port/db")
            db_prefix (str): Prefix for all Redis keys
            expire (Optional[int]): TTL for Redis keys in seconds
            session_table (Optional[str]): Name of the table to store sessions
            runs_table (Optional[str]): Name of the table to store runs (one key per run)
            memory_table (Optional[str]): Name of the table to store memories
            metrics_table (Optional[str]): Name of the table to store metrics
            component_metrics_table (Optional[str]): Name of the table to store the metrics of each agent, team and
                workflow
            user_metrics_table (Optional[str]): Name of the table to store the metrics of each user
            metrics_refreshes_table (Optional[str]): Name of the table to store the metrics refreshes
            eval_table (Optional[str]): Name of the table to store evaluation runs
            knowledge_table (Optional[str]): Name of the table to store knowledge documents
            traces_table (Optional[str]): Name of the table to store traces
            spans_table (Optional[str]): Name of the table to store spans

        Raises:
            ValueError: If neither redis_client nor db_url is provided.
        """
        if id is None:
            base_seed = db_url or str(redis_client)
            seed = f"{base_seed}#{db_prefix}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            runs_table=runs_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            component_metrics_table=component_metrics_table,
            user_metrics_table=user_metrics_table,
            metrics_refreshes_table=metrics_refreshes_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
        )

        if metrics_table is not None:
            log_warning("metrics_table is deprecated; use component_metrics_table and user_metrics_table.")

        self.db_prefix = db_prefix
        self.expire = expire

        # Zero means never refreshed; get_metrics uses this to refresh lazily, at most once per minute.
        # stop_metrics_refresh_on_read sets it to infinity, so reads never calculate
        self._metrics_refreshed_at: float = 0.0
        # The days whose metrics a write could not reopen, retried by the next write
        self._metrics_days_not_reopened: Set[date] = set()

        if redis_client is not None:
            self.redis_client = redis_client
        elif db_url is not None:
            self.redis_client = Redis.from_url(db_url, decode_responses=True)
        else:
            raise ValueError("One of redis_client or db_url must be provided")

    # -- DB methods --

    def table_exists(self, table_name: str) -> bool:
        """Redis implementation, always returns True."""
        return True

    def _get_table_name(self, table_type: str) -> str:
        """Get the active table name for the given table type."""
        if table_type == "sessions":
            return self.session_table_name

        elif table_type == "runs":
            return self.runs_table_name

        elif table_type == "memories":
            return self.memory_table_name

        elif table_type == "metrics":
            return self.metrics_table_name

        elif table_type == "component_metrics":
            return self.component_metrics_table_name

        elif table_type == "user_metrics":
            return self.user_metrics_table_name

        elif table_type == "metrics_refreshes":
            return self.metrics_refreshes_table_name

        elif table_type == "evals":
            return self.eval_table_name

        elif table_type == "knowledge":
            return self.knowledge_table_name

        elif table_type == "traces":
            return self.trace_table_name

        elif table_type == "spans":
            return self.span_table_name

        else:
            raise ValueError(f"Unknown table type: {table_type}")

    def _store_record(
        self, table_type: str, record_id: str, data: Dict[str, Any], index_fields: Optional[List[str]] = None
    ) -> bool:
        """Generic method to store a record in Redis, considering optional indexing.

        Args:
            table_type (str): The type of table to store the record in.
            record_id (str): The ID of the record to store.
            data (Dict[str, Any]): The data to store in the record.
            index_fields (Optional[List[str]]): The fields to index the record by.

        Returns:
            bool: True if the record was stored successfully, False otherwise.
        """
        try:
            key = generate_redis_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)
            serialized_data = serialize_data(data)

            self.redis_client.set(key, serialized_data, ex=self.expire)

            if index_fields:
                create_index_entries(
                    redis_client=self.redis_client,
                    prefix=self.db_prefix,
                    table_type=table_type,
                    record_id=record_id,
                    record_data=data,
                    index_fields=index_fields,
                )

            return True

        except Exception as e:
            log_error(f"Error storing Redis record: {str(e)}")
            return False

    def _get_record(self, table_type: str, record_id: str) -> Optional[Dict[str, Any]]:
        """Generic method to get a record from Redis.

        Args:
            table_type (str): The type of table to get the record from.
            record_id (str): The ID of the record to get.

        Returns:
            Optional[Dict[str, Any]]: The record data if found, None otherwise.
        """
        try:
            key = generate_redis_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)

            data = self.redis_client.get(key)
            if data is None:
                return None

            return deserialize_data(data)  # type: ignore

        except Exception as e:
            log_error(f"Error getting record {record_id}: {str(e)}")
            return None

    def _delete_record(self, table_type: str, record_id: str, index_fields: Optional[List[str]] = None) -> bool:
        """Generic method to delete a record from Redis.

        Args:
            table_type (str): The type of table to delete the record from.
            record_id (str): The ID of the record to delete.
            index_fields (Optional[List[str]]): The fields to index the record by.

        Returns:
            bool: True if the record was deleted successfully, False otherwise.

        Raises:
            Exception: If any error occurs while deleting the record.
        """
        try:
            # Handle index deletion first
            if index_fields:
                record_data = self._get_record(table_type, record_id)
                if record_data:
                    remove_index_entries(
                        redis_client=self.redis_client,
                        prefix=self.db_prefix,
                        table_type=table_type,
                        record_id=record_id,
                        record_data=record_data,
                        index_fields=index_fields,
                    )

            key = generate_redis_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)
            result = self.redis_client.delete(key)
            if result is None or result == 0:
                return False

            return True

        except Exception as e:
            log_error(f"Error deleting record {record_id}: {str(e)}")
            return False

    def _get_all_records(self, table_type: str) -> List[Dict[str, Any]]:
        """Generic method to get all records for a table type.

        Args:
            table_type (str): The type of table to get the records from.

        Returns:
            List[Dict[str, Any]]: The records data if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the records.
        """
        try:
            keys = get_all_keys_for_table(redis_client=self.redis_client, prefix=self.db_prefix, table_type=table_type)

            records = []
            for key in keys:
                data = self.redis_client.get(key)
                if data:
                    records.append(deserialize_data(data))  # type: ignore

            return records

        except Exception as e:
            log_error(f"Error getting all records for {table_type}: {str(e)}")
            return []

    def _schema_version_key(self, table_name: str) -> str:
        """Key holding the schema version stamp for the given table."""
        return f"{self.db_prefix}:{self.versions_table_name}:{table_name}"

    def get_latest_schema_version(self, table_name: str = "") -> Optional[str]:
        """Get the schema version stamped for the given table.

        Defaults to "2.0.0" when nothing is stamped so the MigrationManager
        runs migrations instead of skipping the table.
        """
        value = self.redis_client.get(self._schema_version_key(table_name))
        if value is None:
            return "2.0.0"
        return value.decode() if isinstance(value, bytes) else str(value)

    def upsert_schema_version(self, table_name: str = "", version: str = "") -> None:
        """Record the schema version stamp for the given table.

        No TTL: the stamp must outlive ``self.expire``.
        """
        self.redis_client.set(self._schema_version_key(table_name), version)

    # -- Run methods --

    _RUNS_BY_SESSION_INDEX_PATTERN = "{prefix}:runs:by_session:{session_id}"

    def _runs_by_session_index_key(self, session_id: str) -> str:
        """Sorted-set key listing run_ids for a session, scored by run_index."""
        return self._RUNS_BY_SESSION_INDEX_PATTERN.format(prefix=self.db_prefix, session_id=session_id)

    def upsert_run(
        self,
        run: Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]],
        session_id: str,
        user_id: Optional[str] = None,
        run_index: Optional[int] = None,
    ) -> None:
        """Upsert a single run as its own Redis key + maintain the session index (O(1)).

        Optimized for updating existing runs (e.g., status changes in HITL or
        background mode) without re-upserting all runs in the session.

        For new runs, ``run_index`` should be provided or will be read from
        ``run_data``. For updates to existing runs, ``run_index`` is preserved
        from the original insert.

        Args:
            run: The run object or dictionary to upsert.
            session_id: The session ID this run belongs to.
            user_id: Optional user ID to associate with the run.
            run_index: Optional run index for new runs.

        Raises:
            ValueError: If the run has no run_id.
            Exception: If an error occurs during upsert.
        """
        try:
            row = build_single_run_row(
                run=run,
                session_id=session_id,
                user_id=user_id,
                run_index=run_index,
            )

            # Preserve the original run_index if the row already exists
            existing = self._get_record("runs", row["run_id"])
            if existing is not None and "run_index" in existing:
                row["run_index"] = existing["run_index"]
            # The stored created_at, which a resumed run keeps
            if existing is not None and existing.get("created_at") is not None:
                row["created_at"] = existing["created_at"]

            index_key = self._runs_by_session_index_key(session_id)
            run_key = generate_redis_key(prefix=self.db_prefix, table_type="runs", key_id=row["run_id"])

            pipe = self.redis_client.pipeline()
            pipe.set(run_key, serialize_data(row), ex=self.expire)
            pipe.zadd(index_key, {row["run_id"]: float(row.get("run_index") or 0)})
            if self.expire is not None:
                pipe.expire(index_key, self.expire)
            self._add_metrics_index_entries(pipe, "runs", row["run_id"], row["created_at"])
            pipe.execute()

            # Maintain field indexes for cross-session run queries
            create_index_entries(
                redis_client=self.redis_client,
                prefix=self.db_prefix,
                table_type="runs",
                record_id=row["run_id"],
                record_data=row,
                index_fields=["session_id", "user_id", "agent_id", "team_id", "workflow_id", "run_type", "status"],
            )
            self._reopen_metrics_days([row["created_at"]])
        except Exception as e:
            log_error(f"Exception upserting run into Redis: {str(e)}")
            raise e

    def _get_session_runs_data(self, session_id: str) -> List[Dict[str, Any]]:
        """Get raw run_data dicts for a session, ordered by run_index."""
        index_key = self._runs_by_session_index_key(session_id)
        try:
            run_ids: List[Any] = list(self.redis_client.zrange(index_key, 0, -1))  # type: ignore[arg-type]
        except Exception:
            run_ids = []

        if not run_ids:
            return []

        ordered: List[Dict[str, Any]] = []
        for rid in run_ids:
            run_id = rid.decode() if isinstance(rid, bytes) else str(rid)
            row = self._get_record("runs", run_id)
            if not row:
                continue
            run_data = row.get("run_data")
            if run_data is not None:
                ordered.append(run_data)
        return ordered

    def _get_sessions_runs(self, session_ids: List[str]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """Run dicts for several sessions in one read, used by the search fallback."""
        return self._get_sessions_runs_data(session_ids)

    def _get_sessions_runs_data(self, session_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Get raw run_data dicts for several sessions, grouped by session_id, in two pipelined round trips."""
        if not session_ids:
            return {}
        try:
            pipeline = self.redis_client.pipeline(transaction=False)
            for sid in session_ids:
                pipeline.zrange(self._runs_by_session_index_key(sid), 0, -1)
            run_ids_by_session = {
                sid: [rid.decode() if isinstance(rid, bytes) else str(rid) for rid in run_ids or []]
                for sid, run_ids in zip(session_ids, pipeline.execute())
            }
            all_run_ids = [rid for run_ids in run_ids_by_session.values() for rid in run_ids]
            rows_by_id: Dict[str, Dict[str, Any]] = {}
            if all_run_ids:
                pipeline = self.redis_client.pipeline(transaction=False)
                for rid in all_run_ids:
                    pipeline.get(generate_redis_key(prefix=self.db_prefix, table_type="runs", key_id=rid))
                for rid, data in zip(all_run_ids, pipeline.execute()):
                    if data is not None:
                        rows_by_id[rid] = deserialize_data(data)  # type: ignore[arg-type]
        except Exception as e:
            log_error(f"Error batch-reading runs from Redis, reading per session: {str(e)}")
            return {sid: self._get_session_runs_data(sid) for sid in session_ids}
        return {
            sid: [
                rows_by_id[rid]["run_data"]
                for rid in run_ids
                if rid in rows_by_id and rows_by_id[rid].get("run_data") is not None
            ]
            for sid, run_ids in run_ids_by_session.items()
        }

    def _delete_session_runs(self, session_id: str) -> int:
        """Delete every run row associated with a session (and the session's run index)."""
        index_key = self._runs_by_session_index_key(session_id)
        try:
            run_ids: List[Any] = list(self.redis_client.zrange(index_key, 0, -1))  # type: ignore[arg-type]
        except Exception:
            run_ids = []

        deleted = 0
        for rid in run_ids or []:
            run_id = rid.decode() if isinstance(rid, bytes) else str(rid)
            if self._delete_record(
                table_type="runs",
                record_id=run_id,
                index_fields=["session_id", "user_id", "agent_id", "team_id", "workflow_id", "run_type", "status"],
            ):
                deleted += 1
        # Drop the sorted-set itself
        try:
            self.redis_client.delete(index_key)
            if run_ids:
                self.redis_client.zrem(generate_created_at_index_key(self.db_prefix, "runs"), *run_ids)
        except Exception:
            pass
        return deleted

    def cleanup_legacy_runs_field(self, force: bool = False) -> bool:
        """Unset the legacy ``runs`` field from session records in Redis.

        The v3.0.0 migration intentionally leaves the legacy ``runs`` field in
        place on the session record as a backup. Call this once you have
        verified the migration to reclaim the storage.

        Args:
            force: If True, unset the field even on sessions that still hold
                non-null ``runs`` content (a sign that they were not migrated).
                Defaults to False.

        Returns:
            True if any sessions were touched, False otherwise.
        """
        sessions = self._get_all_records("sessions")

        if not force:
            pending = sum(1 for s in sessions if s.get("runs"))
            if pending > 0:
                raise RuntimeError(
                    f"Refusing to unset {self.session_table_name}.runs: {pending} session(s) still have "
                    "non-null `runs` content. Run MigrationManager(db).up() first, or pass force=True."
                )

        touched = 0
        for session in sessions:
            if "runs" not in session:
                continue
            session.pop("runs", None)
            self._store_record(
                table_type="sessions",
                record_id=session["session_id"],
                data=session,
            )
            touched += 1
        log_info(f"Unset runs on {touched} session record(s)")
        return touched > 0

    def get_run(
        self, run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]]]:
        """Read a single run from Redis."""
        try:
            row = self._get_record("runs", run_id)
            if row is None:
                return None
            if not deserialize:
                return row
            return deserialize_run(row.get("run_type"), row["run_data"])
        except Exception as e:
            log_error(f"Exception reading run: {str(e)}")
            raise e

    def get_runs(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[Union[RunOutput, TeamRunOutput, WorkflowRunOutput]], Tuple[List[Dict[str, Any]], int]]:
        """Get all runs matching the given filters.

        Filters are applied in-memory after fetching candidate rows. When ``session_id``
        is provided, only that session's runs are fetched (cheap, indexed by sorted set).
        """
        try:
            # Fast path: filter by session_id uses the index
            if session_id is not None:
                index_key = self._runs_by_session_index_key(session_id)
                try:
                    run_ids: List[Any] = list(self.redis_client.zrange(index_key, 0, -1))  # type: ignore[arg-type]
                except Exception:
                    run_ids = []
                rows: List[Dict[str, Any]] = []
                for rid in run_ids or []:
                    run_id = rid.decode() if isinstance(rid, bytes) else str(rid)
                    row = self._get_record("runs", run_id)
                    if row is not None:
                        rows.append(row)
            else:
                rows = self._get_all_records("runs")

            conditions: Dict[str, Any] = {}
            if user_id is not None:
                conditions["user_id"] = user_id
            if agent_id is not None:
                conditions["agent_id"] = agent_id
            if team_id is not None:
                conditions["team_id"] = team_id
            if workflow_id is not None:
                conditions["workflow_id"] = workflow_id
            if status is not None:
                conditions["status"] = status.value if isinstance(status, RunStatus) else status
            rows = apply_filters(records=rows, conditions=conditions)
            total_count = len(rows)

            if sort_by is None:
                # Default: ordered by run_index then created_at
                rows = sorted(rows, key=lambda r: (r.get("run_index") or 0, r.get("created_at") or 0))
            else:
                rows = apply_sorting(records=rows, sort_by=sort_by, sort_order=sort_order)

            rows = apply_pagination(records=rows, limit=limit, page=page)

            if not deserialize:
                return rows, total_count
            return [deserialize_run(r.get("run_type"), r["run_data"]) for r in rows]
        except Exception as e:
            log_error(f"Exception reading runs: {str(e)}")
            raise e

    def _scrub_run_ids_from_session_legacy_blob(self, session_id: str, run_ids: set) -> None:
        """Remove ``run_ids`` from the given session's legacy ``runs`` field.

        Partial-migration state: v3 migration copied runs into per-run keys but
        preserved the legacy embedded blob as a backup. Deleting a run row
        alone leaves the blob intact and ``merge_runs_table_with_legacy_blob``
        resurrects it on the next read.
        """
        if not run_ids:
            return
        session = self._get_record("sessions", session_id)
        if session is None:
            return
        legacy = session.get("runs")
        if not isinstance(legacy, list):
            return
        kept = [r for r in legacy if not (isinstance(r, dict) and r.get("run_id") in run_ids)]
        if len(kept) == len(legacy):
            return
        session["runs"] = kept
        self._store_record("sessions", session_id, session)

    def delete_run(self, run_id: str) -> bool:
        """Delete a single run from Redis (and its entry in the session's run index)."""
        try:
            row = self._get_record("runs", run_id)
            if row is None:
                return False
            sid = row.get("session_id")
            ok = self._delete_record(
                table_type="runs",
                record_id=run_id,
                index_fields=["session_id", "user_id", "agent_id", "team_id", "workflow_id", "run_type", "status"],
            )
            if ok and sid:
                try:
                    self.redis_client.zrem(self._runs_by_session_index_key(sid), run_id)
                    self.redis_client.zrem(generate_created_at_index_key(self.db_prefix, "runs"), run_id)
                except Exception:
                    pass
                self._scrub_run_ids_from_session_legacy_blob(sid, {run_id})
            return ok
        except Exception as e:
            log_error(f"Error deleting run: {str(e)}")
            raise e

    def delete_runs(self, run_ids: List[str]) -> None:
        """Delete all given runs."""
        for run_id in run_ids:
            self.delete_run(run_id)

    # -- Session methods --

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session from Redis.

        Args:
            session_id (str): The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the session.
        """
        try:
            if user_id is not None:
                session = self._get_record("sessions", session_id)
                if session is None or session.get("user_id") != user_id:
                    log_debug(f"No session found to delete with session_id: {session_id} and user_id: {user_id}")
                    return False
            if self._delete_record(
                table_type="sessions",
                record_id=session_id,
                index_fields=["user_id", "agent_id", "team_id", "workflow_id", "session_type"],
            ):
                self.redis_client.zrem(generate_created_at_index_key(self.db_prefix, "sessions"), session_id)
                # Cascade-delete runs
                self._delete_session_runs(session_id)
                log_debug(f"Successfully deleted session: {session_id}")
                return True
            else:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False

        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from Redis.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the sessions.
        """
        try:
            deleted_count = 0
            for session_id in session_ids:
                if user_id is not None:
                    session = self._get_record("sessions", session_id)
                    if session is None or session.get("user_id") != user_id:
                        continue
                if self._delete_record(
                    "sessions",
                    session_id,
                    index_fields=["user_id", "agent_id", "team_id", "workflow_id", "session_type"],
                ):
                    self.redis_client.zrem(generate_created_at_index_key(self.db_prefix, "sessions"), session_id)
                    self._delete_session_runs(session_id)
                    deleted_count += 1
            log_debug(f"Successfully deleted {deleted_count} sessions")

        except Exception as e:
            log_error(f"Error deleting sessions: {str(e)}")
            raise e

    def get_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
        runs_limit: Optional[int] = None,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Read a session from Redis.

        Args:
            session_id (str): The ID of the session to get.
            session_type (Optional[SessionType]): The type of session to get.
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            Optional[Union[AgentSession, TeamSession, WorkflowSession]]: The session if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the session.
        """
        try:
            session = self._get_record("sessions", session_id)
            if session is None:
                return None

            # Apply filters
            if user_id is not None and session.get("user_id") != user_id:
                return None

            # Attach runs from the runs keys, merged with any legacy `runs` blob
            runs_data = self._get_session_runs_data(session_id)
            session["runs"] = merge_runs_table_with_legacy_blob(runs_data, session.get("runs"))

            if runs_limit is not None:
                session["runs"] = filter_context_runs(session.get("runs") or [])[-runs_limit:]

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Exception reading session: {str(e)}")
            raise e

    # TODO: optimizable
    def get_sessions(
        self,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
        create_index_if_not_found: Optional[bool] = True,
        include_runs: bool = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        """Get all sessions matching the given filters.

        Args:
            session_type (Optional[SessionType]): The type of session to filter by.
            user_id (Optional[str]): The ID of the user to filter by.
            component_id (Optional[str]): The ID of the component to filter by.
            session_name (Optional[str]): The name of the session to filter by.
            limit (Optional[int]): The maximum number of sessions to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The order to sort by.

        Returns:
            List[Union[AgentSession, TeamSession, WorkflowSession]]: The list of sessions.
        """
        try:
            all_sessions = self._get_all_records("sessions")

            conditions: Dict[str, Any] = {}
            if session_type is not None:
                conditions["session_type"] = session_type
            if user_id is not None:
                conditions["user_id"] = user_id

            filtered_sessions = apply_filters(records=all_sessions, conditions=conditions)

            if component_id is not None:
                if session_type == SessionType.AGENT:
                    filtered_sessions = [s for s in filtered_sessions if s.get("agent_id") == component_id]
                elif session_type == SessionType.TEAM:
                    filtered_sessions = [s for s in filtered_sessions if s.get("team_id") == component_id]
                elif session_type == SessionType.WORKFLOW:
                    filtered_sessions = [s for s in filtered_sessions if s.get("workflow_id") == component_id]
                elif session_type is None:
                    filtered_sessions = [
                        s
                        for s in filtered_sessions
                        if s.get("agent_id") == component_id
                        or s.get("team_id") == component_id
                        or s.get("workflow_id") == component_id
                    ]
            if start_timestamp is not None:
                filtered_sessions = [s for s in filtered_sessions if s.get("created_at", 0) >= start_timestamp]
            if end_timestamp is not None:
                filtered_sessions = [s for s in filtered_sessions if s.get("created_at", 0) <= end_timestamp]

            if session_name is not None:
                filtered_sessions = [
                    s
                    for s in filtered_sessions
                    if session_name.lower() in ((s.get("session_data") or {}).get("session_name") or "").lower()
                ]

            sorted_sessions = apply_sorting(records=filtered_sessions, sort_by=sort_by, sort_order=sort_order)
            sessions = apply_pagination(records=sorted_sessions, limit=limit, page=page)
            sessions = [record for record in sessions]

            # Attach runs from the runs keys, merged with any legacy `runs` blob
            for s in sessions:
                if not include_runs:
                    # Search scans skip the runs keys; the record's legacy runs field is kept for merging later.
                    continue
                runs_data = self._get_session_runs_data(s["session_id"])
                s["runs"] = merge_runs_table_with_legacy_blob(runs_data, s.get("runs"))

            if not deserialize:
                return sessions, len(filtered_sessions)

            return deserialize_sessions(session_type, sessions)

        except Exception as e:
            log_error(f"Exception reading sessions: {str(e)}")
            raise e

    def rename_session(
        self,
        session_id: str,
        session_type: Optional[SessionType],
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Rename a session in Redis.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name of the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Session]: The renamed session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while renaming the session.
        """
        try:
            session = self._get_record("sessions", session_id)
            if session is None:
                return None

            if user_id is not None and session.get("user_id") != user_id:
                return None

            if session_type is not None and session.get("session_type") != session_type.value:
                return None

            # Update session_name, in session_data
            if "session_data" not in session or session["session_data"] is None:
                session["session_data"] = {}
            session["session_data"]["session_name"] = session_name
            session["updated_at"] = int(time.time())

            # Don't drop the runs field on rename; if it existed it stays. Persist without runs in v3 shape.
            session_to_store = {k: v for k, v in session.items() if k != "runs"}
            success = self._store_record("sessions", session_id, session_to_store)
            if not success:
                return None

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

            # Attach runs from the runs keys for the returned object
            runs_data = self._get_session_runs_data(session_id)
            session["runs"] = merge_runs_table_with_legacy_blob(runs_data, session.get("runs"))

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Error renaming session: {str(e)}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update a session in Redis.

        Args:
            session (Session): The session to upsert.

        Returns:
            Optional[Session]: The upserted session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while upserting the session.
        """
        try:
            session_dict = session.to_dict(include_runs=False)

            existing = self._get_record(table_type="sessions", record_id=session.session_id)
            if (
                existing
                and existing.get("user_id") is not None
                and existing.get("user_id") != session_dict.get("user_id")
            ):
                return None

            data: Dict[str, Any]
            if isinstance(session, AgentSession):
                data = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.AGENT.value,
                    "agent_id": session_dict.get("agent_id"),
                    "team_id": session_dict.get("team_id"),
                    "workflow_id": session_dict.get("workflow_id"),
                    "user_id": session_dict.get("user_id"),
                    "agent_data": session_dict.get("agent_data"),
                    "team_data": session_dict.get("team_data"),
                    "workflow_data": session_dict.get("workflow_data"),
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at") or int(time.time()),
                    "updated_at": int(time.time()),
                }
                index_fields = ["user_id", "agent_id", "session_type"]
            elif isinstance(session, TeamSession):
                data = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.TEAM.value,
                    "agent_id": None,
                    "team_id": session_dict.get("team_id"),
                    "workflow_id": None,
                    "user_id": session_dict.get("user_id"),
                    "team_data": session_dict.get("team_data"),
                    "agent_data": None,
                    "workflow_data": None,
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at") or int(time.time()),
                    "updated_at": int(time.time()),
                }
                index_fields = ["user_id", "team_id", "session_type"]
            elif isinstance(session, WorkflowSession):
                data = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.WORKFLOW.value,
                    "workflow_id": session_dict.get("workflow_id"),
                    "user_id": session_dict.get("user_id"),
                    "workflow_data": session_dict.get("workflow_data"),
                    "session_data": session_dict.get("session_data"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at") or int(time.time()),
                    "updated_at": int(time.time()),
                    "agent_id": None,
                    "team_id": None,
                    "agent_data": None,
                    "team_data": None,
                    "summary": None,
                }
                index_fields = ["user_id", "workflow_id", "session_type"]
            else:
                raise ValueError(f"Invalid session type: {session.session_type}")

            # Preserve the legacy `runs` field as a frozen backup. _store_record replaces
            # the whole record, so carry any existing legacy blob forward; runs now live in
            # their own keys. Only cleanup_legacy_runs_field() reclaims it. Dropping it here
            # would lose history for sessions not yet migrated.
            if existing and existing.get("runs") is not None:
                data["runs"] = existing["runs"]
            # The stored created_at, which keeps the session on the day it was created
            if existing and existing.get("created_at") is not None:
                data["created_at"] = existing["created_at"]

            success = self._store_record(
                table_type="sessions",
                record_id=session.session_id,
                data=data,
                index_fields=index_fields,
            )
            if not success:
                return None

            pipe = self.redis_client.pipeline()
            self._add_metrics_index_entries(pipe, "sessions", session.session_id, data["created_at"])
            pipe.execute()
            if get_metrics_reopen_session_ids([existing] if existing else [], [data]):
                self._reopen_metrics_days([data["created_at"]])

            # Runs are persisted separately via upsert_run by the caller (agent loop).
            # Attach the in-memory runs for callers.
            data["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]

            if not deserialize:
                return data

            return deserialize_session(None, data)

        except Exception as e:
            log_error(f"Error upserting session: {str(e)}")
            raise e

    def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[Session, Dict[str, Any]]]:
        """
        Bulk upsert multiple sessions for improved performance on large datasets.

        Args:
            sessions (List[Session]): List of sessions to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not sessions:
            return []

        try:
            log_info(
                f"RedisDb doesn't support efficient bulk operations, falling back to individual upserts for {len(sessions)} sessions"
            )

            # Fall back to individual upserts
            results = []
            for session in sessions:
                if session is not None:
                    result = self.upsert_session(session, deserialize=deserialize)
                    if result is not None:
                        results.append(result)
            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert: {str(e)}")
            return []

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from Redis.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user. If provided, verifies the memory belongs to this user before deleting.

        Returns:
            bool: True if the memory was deleted, False otherwise.

        Raises:
            Exception: If any error occurs while deleting the memory.
        """
        try:
            # If user_id is provided, verify ownership before deleting
            if user_id is not None:
                memory = self._get_record("memories", memory_id)
                if memory is None:
                    log_debug(f"No user memory found with id: {memory_id}")
                    return
                if memory.get("user_id") != user_id:
                    log_debug(f"Memory {memory_id} does not belong to user {user_id}")
                    return

            if self._delete_record(
                "memories", memory_id, index_fields=["user_id", "agent_id", "team_id", "workflow_id"]
            ):
                log_debug(f"Successfully deleted user memory id: {memory_id}")
            else:
                log_debug(f"No user memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting user memory: {str(e)}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from Redis.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user. If provided, only deletes memories belonging to this user.
        """
        try:
            # TODO: cant we optimize this?
            for memory_id in memory_ids:
                # If user_id is provided, verify ownership before deleting
                if user_id is not None:
                    memory = self._get_record("memories", memory_id)
                    if memory is None:
                        continue
                    if memory.get("user_id") != user_id:
                        log_debug(f"Memory {memory_id} does not belong to user {user_id}, skipping deletion")
                        continue

                self._delete_record(
                    "memories",
                    memory_id,
                    index_fields=["user_id", "agent_id", "team_id", "workflow_id"],
                )

        except Exception as e:
            log_error(f"Error deleting user memories: {str(e)}")
            raise e

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from Redis.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            List[str]: The list of memory topics.
        """
        try:
            all_memories = self._get_all_records("memories")

            topics = set()
            for memory in all_memories:
                if user_id is not None and memory.get("user_id") != user_id:
                    continue
                memory_topics = memory.get("topics", [])
                if isinstance(memory_topics, list):
                    topics.update(memory_topics)

            return list(topics)

        except Exception as e:
            log_error(f"Exception reading memory topics: {str(e)}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from Redis.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user. If provided, only returns the memory if it belongs to this user.

        Returns:
            Optional[UserMemory]: The memory data if found, None otherwise.
        """
        try:
            memory_raw = self._get_record("memories", memory_id)
            if memory_raw is None:
                return None

            # Filter by user_id if provided
            if user_id is not None and memory_raw.get("user_id") != user_id:
                return None

            if not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception reading memory: {str(e)}")
            raise e

    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
        """Get all memories from Redis as UserMemory objects.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            topics (Optional[List[str]]): The topics to filter by.
            search_content (Optional[str]): The content to search for.
            limit (Optional[int]): The maximum number of memories to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The order to sort by.
            deserialize (Optional[bool]): Whether to deserialize the memories.

        Returns:
            Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of UserMemory objects
                - When deserialize=False: Tuple of (memory dictionaries, total count)

        Raises:
            Exception: If any error occurs while reading the memories.
        """
        try:
            all_memories = self._get_all_records("memories")

            # Apply filters
            conditions = {}
            if user_id is not None:
                conditions["user_id"] = user_id
            if agent_id is not None:
                conditions["agent_id"] = agent_id
            if team_id is not None:
                conditions["team_id"] = team_id

            filtered_memories = apply_filters(records=all_memories, conditions=conditions)

            # Apply topic filter
            if topics is not None:
                filtered_memories = [
                    m for m in filtered_memories if any(topic in m.get("topics", []) for topic in topics)
                ]

            # Apply content search
            if search_content is not None:
                filtered_memories = [
                    m for m in filtered_memories if search_content.lower() in str(m.get("memory", "")).lower()
                ]

            sorted_memories = apply_sorting(records=filtered_memories, sort_by=sort_by, sort_order=sort_order)
            paginated_memories = apply_pagination(records=sorted_memories, limit=limit, page=page)

            if not deserialize:
                return paginated_memories, len(filtered_memories)

            return [UserMemory.from_dict(record) for record in paginated_memories]

        except Exception as e:
            log_error(f"Exception reading memories: {str(e)}")
            raise e

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memory stats from Redis.

        Args:
            limit (Optional[int]): The maximum number of stats to return.
            page (Optional[int]): The page number to return.
            user_id (Optional[str]): User ID for filtering.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the list of stats and the total number of stats.

        Raises:
            Exception: If any error occurs while getting the user memory stats.
        """
        try:
            all_memories = self._get_all_records("memories")

            # Group by user_id
            user_stats = {}
            for memory in all_memories:
                memory_user_id = memory.get("user_id")
                # filter by user_id if provided
                if user_id is not None and memory_user_id != user_id:
                    continue
                if memory_user_id is None:
                    continue

                if memory_user_id not in user_stats:
                    user_stats[memory_user_id] = {
                        "user_id": memory_user_id,
                        "total_memories": 0,
                        "last_memory_updated_at": 0,
                    }

                user_stats[memory_user_id]["total_memories"] += 1
                updated_at = memory.get("updated_at", 0)
                if updated_at > user_stats[memory_user_id]["last_memory_updated_at"]:
                    user_stats[memory_user_id]["last_memory_updated_at"] = updated_at

            stats_list = list(user_stats.values())

            # Sorting by last_memory_updated_at descending
            stats_list.sort(key=lambda x: x["last_memory_updated_at"], reverse=True)

            total_count = len(stats_list)

            paginated_stats = apply_pagination(records=stats_list, limit=limit, page=page)

            return paginated_stats, total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {str(e)}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in Redis.

        Args:
            memory (UserMemory): The memory to upsert.

        Returns:
            Optional[UserMemory]: The upserted memory data if successful, None otherwise.
        """
        try:
            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            data = {
                "user_id": memory.user_id,
                "agent_id": memory.agent_id,
                "team_id": memory.team_id,
                "memory_id": memory.memory_id,
                "memory": memory.memory,
                "topics": memory.topics,
                "input": memory.input,
                "feedback": memory.feedback,
                "created_at": memory.created_at,
                "updated_at": int(time.time()),
            }

            success = self._store_record(
                "memories", memory.memory_id, data, index_fields=["user_id", "agent_id", "team_id", "workflow_id"]
            )

            if not success:
                return None

            if not deserialize:
                return data

            return UserMemory.from_dict(data)

        except Exception as e:
            log_error(f"Error upserting user memory: {str(e)}")
            raise e

    def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk upsert multiple user memories for improved performance on large datasets.

        Args:
            memories (List[UserMemory]): List of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not memories:
            return []

        try:
            log_info(
                f"RedisDb doesn't support efficient bulk operations, falling back to individual upserts for {len(memories)} memories"
            )

            # Fall back to individual upserts
            results = []
            for memory in memories:
                if memory is not None:
                    result = self.upsert_user_memory(memory, deserialize=deserialize)
                    if result is not None:
                        results.append(result)
            return results

        except Exception as e:
            log_error(f"Exception during bulk memory upsert: {str(e)}")
            return []

    def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            # Get all keys for memories table
            keys = get_all_keys_for_table(redis_client=self.redis_client, prefix=self.db_prefix, table_type="memories")

            if keys:
                # Delete all memory keys in a single batch operation
                self.redis_client.delete(*keys)

        except Exception as e:
            log_error(f"Exception deleting all memories: {str(e)}")
            raise e

    # -- Metrics methods --

    def _metrics_prefix(self) -> str:
        """Prefix of every key of the metrics tables, which share one cluster slot."""
        return generate_metrics_prefix(self.db_prefix)

    def _metrics_refresh_key(self) -> str:
        """Key holding the one row of the metrics refreshes table, which one refresh at a time holds."""
        return generate_redis_key(
            prefix=self._metrics_prefix(), table_type="metrics_refreshes", key_id=METRICS_REFRESH_ID
        )

    def _metrics_index_key(self) -> str:
        """Key holding the sessions schema version at which the sessions and runs were last indexed by created_at, and
        whether a session held legacy runs then."""
        return f"{self._metrics_prefix()}:metrics_index"

    def _add_metrics_index_entries(self, pipe: Any, table_type: str, record_id: str, created_at: Optional[int]) -> None:
        """Add a session or run to the sorted set that lists its table by created_at, in the given pipeline.

        Args:
            pipe (Any): The pipeline of the write.
            table_type (str): "sessions" or "runs".
            record_id (str): The ID of the session or run.
            created_at (Optional[int]): Its stored created_at.
        """
        if created_at is None:
            return
        index_key = generate_created_at_index_key(self.db_prefix, table_type)
        pipe.zadd(index_key, {record_id: created_at})
        if self.expire is not None:
            pipe.expire(index_key, self.expire)

    def _reopen_metrics_days(self, created_ats: Sequence[Optional[int]]) -> None:
        """Reopen the metrics of each day a write changed, right after the write, so the next calculation rebuilds
        it.

        A failed reopen never fails the write itself, and the days it could not reopen are retried by the next write.

        Args:
            created_ats (Sequence[Optional[int]]): The stored created_at of each run or session the write changed.
        """
        days = sorted(
            {day for created_at in created_ats if (day := metrics_day_to_reopen(created_at)) is not None}
            | self._metrics_days_not_reopened
        )
        if not days:
            return
        try:
            # No metrics were calculated yet: the first calculation builds every day
            if not self.redis_client.exists(self._metrics_refresh_key()):
                self._metrics_days_not_reopened.clear()
                return
            pipe = self.redis_client.pipeline()
            for day in days:
                reopen_metrics_day(pipe, self._metrics_prefix(), day, self.expire)
            pipe.execute()
            self._metrics_days_not_reopened.difference_update(days)
        except Exception as e:
            self._metrics_days_not_reopened.update(days)
            log_warning(
                f"Could not reopen the metrics of {', '.join(str(day) for day in days)}: {database_error_message(e)}"
            )

    def _get_metrics_refresh_row(self) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get the row of the metrics refreshes table, and the locked_at at or before which its lock is stale, by the
        Redis server's clock."""
        raw = self.redis_client.get(self._metrics_refresh_key())
        stale_lock_threshold = self._q_server_now() - METRICS_LOCK_SECONDS
        if raw is None:
            return None, stale_lock_threshold
        return json.loads(raw if isinstance(raw, str) else raw.decode()), stale_lock_threshold  # type: ignore[union-attr]

    def _claim_metrics_refresh(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Claim the row of the metrics refreshes table, so one process calculates metrics at a time.

        Args:
            worker_id (str): The id of this calculation, which heartbeats and releases the claim.

        Returns:
            Optional[Dict[str, Any]]: The claimed row, with when the last calculation finished and its fingerprint.
                None when another process holds it.
        """
        from redis.exceptions import WatchError

        refresh_key = self._metrics_refresh_key()
        try:
            with self.redis_client.pipeline(transaction=True) as pipe:
                # A claim racing this one changes the row after the watch, which fails this one
                pipe.watch(refresh_key)
                raw = pipe.get(refresh_key)
                stored_row = json.loads(raw if isinstance(raw, str) else raw.decode()) if raw is not None else None
                now = self._q_server_now()
                # A stale lock is taken over: the process that held it stopped
                if (
                    stored_row is not None
                    and stored_row["locked_by"] is not None
                    and stored_row["locked_at"] > now - METRICS_LOCK_SECONDS
                ):
                    pipe.unwatch()
                    return None
                refresh_row = {
                    "id": METRICS_REFRESH_ID,
                    "finished_at": None,
                    "fingerprint": None,
                    **(stored_row or {}),
                    "locked_by": worker_id,
                    "locked_at": now,
                    "started_at": now,
                    "status": "running",
                    "error": None,
                }
                pipe.multi()
                pipe.set(refresh_key, json.dumps(refresh_row))
                pipe.execute()
                return refresh_row
        except WatchError:
            return None

    def _mark_metrics_refresh_rebuild(self) -> bool:
        """Write a mark no fingerprint equals on the row of the metrics refreshes table, so the next calculation
        rebuilds yesterday and today. False when a calculation's write conflicted with it through every try."""
        from redis.exceptions import WatchError

        refresh_key = self._metrics_refresh_key()
        for _ in range(10):
            try:
                with self.redis_client.pipeline(transaction=True) as pipe:
                    pipe.watch(refresh_key)
                    raw = pipe.get(refresh_key)
                    if raw is None:
                        pipe.unwatch()
                        return True
                    stored_row = json.loads(raw if isinstance(raw, str) else raw.decode())
                    pipe.multi()
                    pipe.set(refresh_key, json.dumps({**stored_row, "fingerprint": ["rebuild", uuid4().hex]}))
                    pipe.execute()
                    return True
            except WatchError:
                continue  # the refresh changed under us; re-read and re-check
        return False

    def _heartbeat_metrics_refresh(self, worker_id: str) -> bool:
        """Refresh locked_at for this worker's metrics refresh. False when another process took it over."""
        from redis.exceptions import WatchError

        refresh_key = self._metrics_refresh_key()
        for _ in range(10):
            try:
                with self.redis_client.pipeline(transaction=True) as pipe:
                    pipe.watch(refresh_key)
                    raw = pipe.get(refresh_key)
                    refresh_row = json.loads(raw if isinstance(raw, str) else raw.decode()) if raw is not None else {}
                    if refresh_row.get("locked_by") != worker_id:
                        pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.set(refresh_key, json.dumps({**refresh_row, "locked_at": self._q_server_now()}))
                    pipe.execute()
                    return True
            except WatchError:
                continue  # the refresh changed under us; re-read and re-check
        return False

    def _release_metrics_refresh(
        self,
        worker_id: Optional[str],
        error: Optional[str] = None,
        fingerprint: Optional[List[Any]] = None,
        stopped: bool = False,
        claimed_fingerprint: Optional[List[Any]] = None,
        started_at: Optional[int] = None,
        finished_at: Optional[int] = None,
    ) -> None:
        """Release the row of the metrics refreshes table: completed, with the fingerprint, without an error, failed
        with one, and as the last completed refresh left it when the calculation stopped. A worker_id of None writes
        the row only while no process holds it and no calculation started or finished after the read of started_at
        and finished_at, and creates it when that read found none."""
        from redis.exceptions import WatchError

        refresh_key = self._metrics_refresh_key()
        try:
            for _ in range(10):
                try:
                    with self.redis_client.pipeline(transaction=True) as pipe:
                        pipe.watch(refresh_key)
                        raw = pipe.get(refresh_key)
                        refresh_row = (
                            json.loads(raw if isinstance(raw, str) else raw.decode()) if raw is not None else {}
                        )
                        if worker_id is None and error is not None and started_at is None:
                            # Before any refresh there is no row to update; one created since keeps its own status
                            if raw is not None:
                                pipe.unwatch()
                                return
                            refresh_row = {
                                "id": METRICS_REFRESH_ID,
                                "started_at": self._q_server_now(),
                                "finished_at": None,
                                "fingerprint": None,
                            }
                        elif (
                            raw is None
                            or refresh_row.get("locked_by") != worker_id
                            or (
                                worker_id is None
                                and (refresh_row.get("started_at"), refresh_row.get("finished_at"))
                                != (started_at, finished_at)
                            )
                        ):
                            pipe.unwatch()
                            return
                        refresh_row.update(locked_by=None, locked_at=None)
                        if stopped:
                            # The days it did not reach stay open for the next calculation; a first one that stopped
                            # has none to show
                            finished = refresh_row.get("finished_at") is not None
                            refresh_row.update(
                                status="completed" if finished else "failed",
                                error=None if finished else METRICS_STOPPED_ERROR,
                            )
                        elif error is None:
                            # A rebuild that marked the fingerprint after the claim keeps its mark, so the next
                            # calculation rebuilds yesterday and today
                            stored_fingerprint = refresh_row.get("fingerprint")
                            refresh_row.update(
                                status="completed",
                                error=None,
                                finished_at=self._q_server_now(),
                                fingerprint=stored_fingerprint
                                if stored_fingerprint != claimed_fingerprint
                                else fingerprint,
                            )
                        else:
                            refresh_row.update(status="failed", error=error)
                        pipe.multi()
                        pipe.set(refresh_key, json.dumps(refresh_row))
                        pipe.execute()
                        return
                except WatchError:
                    continue  # the refresh changed under us; re-read and re-check
        except Exception as e:
            log_debug(f"Error releasing metrics refresh: {e}")

    def _get_metrics_index_state(self, worker_id: str, force: bool = False) -> Optional[Dict[str, Any]]:
        """Get the state of the sorted sets that list the sessions and runs by created_at, indexing every session and
        run first when they were never indexed, when the v3 migration copied runs since, or when forced.

        Sessions and runs written before this release, and runs the v3 migration copies, are in no sorted set, so they
        are read once here, a batch at a time.

        Args:
            worker_id (str): The id of the calculation holding the metrics refresh, heartbeated with every batch.
            force (bool): Index every session and run again, as a rebuild does for the ones a process of an earlier
                release saved since.

        Returns:
            Optional[Dict[str, Any]]: The sessions schema version they were indexed at, and whether a session held
                legacy runs then. None when the metrics refresh was taken over.
        """
        schema_version = self.get_latest_schema_version(self.session_table_name)
        raw = self.redis_client.get(self._metrics_index_key())
        index_state = json.loads(raw if isinstance(raw, str) else raw.decode()) if raw is not None else None  # type: ignore[union-attr]
        if not force and index_state is not None and index_state["schema_version"] == schema_version:
            return index_state

        legacy_runs = False
        for table_type in ["sessions", "runs"]:
            keys = get_all_keys_for_table(
                redis_client=self.redis_client, prefix=self.db_prefix, table_type=table_type, count=METRICS_SCAN_COUNT
            )
            key_prefix = generate_redis_key(prefix=self.db_prefix, table_type=table_type, key_id="")
            for batch_start in range(0, len(keys), METRICS_BATCH_SIZE):
                if not self._heartbeat_metrics_refresh(worker_id):
                    return None
                batch_keys = [
                    key.decode() if isinstance(key, bytes) else str(key)
                    for key in keys[batch_start : batch_start + METRICS_BATCH_SIZE]
                ]
                pipeline = self.redis_client.pipeline(transaction=False)
                for key in batch_keys:
                    pipeline.get(key)
                index_pipeline = self.redis_client.pipeline(transaction=False)
                for key, data in zip(batch_keys, pipeline.execute()):
                    if not data:
                        continue
                    record = deserialize_data(data)
                    if record.get("created_at") is None:
                        continue
                    index_pipeline.zadd(
                        generate_created_at_index_key(self.db_prefix, table_type),
                        {key[len(key_prefix) :]: record["created_at"]},
                    )
                    if table_type == "sessions" and isinstance(record.get("runs"), list) and record["runs"]:
                        legacy_runs = True
                index_pipeline.execute()

        index_state = {"schema_version": schema_version, "legacy_runs": legacy_runs}
        self.redis_client.set(self._metrics_index_key(), json.dumps(index_state))
        return index_state

    def _get_metrics_fingerprint(self, yesterday: date) -> Optional[List[Any]]:
        """Get the count and update times of the sessions and runs of yesterday and today. None while one of them was
        updated in the current second, which a second update in that same second would leave unchanged."""
        records = {
            table_type: [
                record
                for day in [yesterday, yesterday + timedelta(days=1)]
                for record in self._get_metrics_day_records(
                    table_type,
                    day,
                    lambda record: {"created_at": record.get("created_at"), "updated_at": record.get("updated_at")},
                )
                or []
            ]
            for table_type in ["sessions", "runs"]
        }
        return get_metrics_fingerprint(records["sessions"], records["runs"], yesterday)

    def _get_metrics_days_with_data(self, today: date) -> Set[date]:
        """Get every day up to today with a session or a run, one sorted set lookup per day found."""
        days: Set[date] = set()
        for table_type in ["sessions", "runs"]:
            index_key = generate_created_at_index_key(self.db_prefix, table_type)
            min_score: Any = "-inf"
            while True:
                first = self.redis_client.zrangebyscore(index_key, min_score, "+inf", start=0, num=1, withscores=True)
                if not first:
                    break
                day = datetime.fromtimestamp(first[0][1], tz=timezone.utc).date()  # type: ignore[index, arg-type]
                if day > today:
                    break
                days.add(day)
                min_score = metrics_day_start(day + timedelta(days=1))
        return days

    def _get_metrics_record_ids(self, table_type: str, index_field: str, index_values: List[str]) -> List[str]:
        """Get the IDs of the component metrics or user metrics rows indexed under any of the given values of a
        field.

        Args:
            table_type (str): "component_metrics" or "user_metrics".
            index_field (str): The indexed field: "date" or "user_id".
            index_values (List[str]): The values of the field.

        Returns:
            List[str]: The record IDs.
        """
        record_ids: Set[str] = set()
        for batch_start in range(0, len(index_values), METRICS_BATCH_SIZE):
            pipeline = self.redis_client.pipeline(transaction=False)
            for index_value in index_values[batch_start : batch_start + METRICS_BATCH_SIZE]:
                pipeline.smembers(generate_index_key(self._metrics_prefix(), table_type, index_field, index_value))
            record_ids.update(
                record_id.decode() if isinstance(record_id, bytes) else str(record_id)
                for batch_record_ids in pipeline.execute()
                for record_id in batch_record_ids
            )
        return sorted(record_ids)

    def _get_component_metrics_records(self, record_ids: List[str]) -> List[Dict[str, Any]]:
        """Get the component metrics rows with the given IDs, a batch at a time, with their date read back as a
        date."""
        records: List[Dict[str, Any]] = []
        for batch_start in range(0, len(record_ids), METRICS_BATCH_SIZE):
            pipeline = self.redis_client.pipeline(transaction=False)
            for record_id in record_ids[batch_start : batch_start + METRICS_BATCH_SIZE]:
                pipeline.get(
                    generate_redis_key(prefix=self._metrics_prefix(), table_type="component_metrics", key_id=record_id)
                )
            records.extend(deserialize_component_metrics_record(data) for data in pipeline.execute() if data)
        return records

    def _get_user_metrics_records(self, record_ids: List[str]) -> List[Dict[str, Any]]:
        """Get the user metrics rows with the given IDs, a batch at a time, each with its version and its date
        read back as a date."""
        records: List[Dict[str, Any]] = []
        for batch_start in range(0, len(record_ids), METRICS_BATCH_SIZE):
            pipeline = self.redis_client.pipeline(transaction=False)
            for record_id in record_ids[batch_start : batch_start + METRICS_BATCH_SIZE]:
                pipeline.hgetall(
                    generate_redis_key(prefix=self._metrics_prefix(), table_type="user_metrics", key_id=record_id)
                )
            records.extend(deserialize_user_metrics_record(fields) for fields in pipeline.execute() if fields)
        return records

    def _get_user_metrics_version(self, aggregation_period: str, record_date: date) -> Optional[int]:
        """Get the version of the everyone row of the given period. None when it has none."""
        version = self.redis_client.hget(
            generate_redis_key(
                prefix=self._metrics_prefix(),
                table_type="user_metrics",
                key_id=user_metrics_record_id(aggregation_period, record_date, ""),
            ),
            "version",
        )
        return int(version) if version is not None else None  # type: ignore[arg-type]

    def _get_user_metrics_column(self, record_ids: List[str], column: str) -> List[Any]:
        """Get one column of each of the given rows of the user metrics table, a batch at a time. None for a row
        that has none."""
        values: List[Any] = []
        for batch_start in range(0, len(record_ids), METRICS_BATCH_SIZE):
            pipeline = self.redis_client.pipeline(transaction=False)
            for record_id in record_ids[batch_start : batch_start + METRICS_BATCH_SIZE]:
                pipeline.hget(
                    generate_redis_key(prefix=self._metrics_prefix(), table_type="user_metrics", key_id=record_id),
                    column,
                )
            values.extend(json.loads(value) if value is not None else None for value in pipeline.execute())
        return values

    def _get_metrics_everyone_record_ids(self) -> List[str]:
        """Get the ID of every everyone row of the user metrics table, of days and of months. Every calculated day has
        one, so their dates are the days metrics were calculated for."""
        return self._get_metrics_record_ids("user_metrics", "user_id", [""])

    def _get_metrics_records_of_days(
        self, table_type: str, starting_date: Optional[date], ending_date: Optional[date]
    ) -> List[str]:
        """Get the IDs of the day rows of a metrics table in the given date range, from the index by date of the
        days metrics were calculated for."""
        days = sorted(
            {
                day
                for day, aggregation_period in map(metrics_record_key, self._get_metrics_everyone_record_ids())
                if aggregation_period == "daily"
                and (starting_date is None or day >= starting_date)
                and (ending_date is None or day <= ending_date)
            }
        )
        return [
            record_id
            for record_id in self._get_metrics_record_ids(table_type, "date", [day.isoformat() for day in days])
            if metrics_record_key(record_id)[1] == "daily"
        ]

    def _get_metrics_dates_to_calculate(
        self, refresh_row: Dict[str, Any], rebuild_from: Optional[date] = None
    ) -> Tuple[List[date], Optional[List[Any]]]:
        """Get the days whose metrics a calculation rebuilds, and the fingerprint of yesterday and today:

        1. Yesterday and today, when their sessions or runs were written since the last calculation.
        2. Every earlier day still open: not yet completed, or reopened by a write since.
        3. Until a first calculation has finished, every day with a session or a run that is not yet completed.
        4. Every earlier day from the day before the last calculation finished, whose writes reopened nothing while
           it was yesterday or today.
        5. With rebuild_from, every day with a session or a run from that date on.

        Args:
            refresh_row (Dict[str, Any]): The row of the metrics refreshes table, from _claim_metrics_refresh.
            rebuild_from (Optional[date]): The first day of a rebuild.

        Returns:
            Tuple[List[date], Optional[List[Any]]]: The days, oldest first, and the fingerprint to keep on the row of
                the metrics refreshes table.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        dates_to_process: Set[date] = set()
        fingerprint = self._get_metrics_fingerprint(yesterday)
        first_calculation = refresh_row["finished_at"] is None
        if first_calculation or fingerprint is None or fingerprint != refresh_row["fingerprint"]:
            dates_to_process.update([yesterday, today])

        # The everyone rows of every calculated day, with whether each is completed
        record_ids = [
            record_id
            for record_id in self._get_metrics_everyone_record_ids()
            if metrics_record_key(record_id)[1] == "daily"
        ]
        completed_by_day = {
            metrics_record_key(record_id)[0]: bool(completed)
            for record_id, completed in zip(record_ids, self._get_user_metrics_column(record_ids, "completed"))
        }
        dates_to_process.update(day for day, completed in completed_by_day.items() if not completed and day < yesterday)
        if not first_calculation:
            dates_to_process.update(metrics_days_since_last_calculation(refresh_row["finished_at"], yesterday))

        if first_calculation or rebuild_from is not None:
            # Only days with data, so one session dated long ago never builds every empty day since
            for data_date in self._get_metrics_days_with_data(today):
                # A rebuild takes every day with data from its first day, completed or not
                rebuilt = rebuild_from is not None and data_date >= rebuild_from
                if rebuilt or (first_calculation and not completed_by_day.get(data_date)):
                    dates_to_process.add(data_date)

        return sorted(dates_to_process), fingerprint

    def _get_open_metrics_months(self) -> List[date]:
        """Get the first day of every month before the current one whose month row is still open: not completed yet,
        or reopened by a day a calculation rebuilt before it stopped."""
        current_month = datetime.now(timezone.utc).date().replace(day=1)
        record_ids = [
            record_id
            for record_id in self._get_metrics_everyone_record_ids()
            if metrics_record_key(record_id)[1] == "monthly" and metrics_record_key(record_id)[0] < current_month
        ]
        return [
            metrics_record_key(record_id)[0]
            for record_id, completed in zip(record_ids, self._get_user_metrics_column(record_ids, "completed"))
            if not completed
        ]

    def _get_metrics_legacy_runs(
        self, start_timestamp: int, end_timestamp: int, worker_id: str
    ) -> Optional[Tuple[Dict[date, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]]:
        """Get the runs not yet migrated out of the sessions' legacy runs field, created in the given time range.

        Sessions have no index by the runs they hold, so every session is read, a batch at a time, and each legacy
        run is reduced to what component metrics count before the next is read.

        Args:
            start_timestamp (int): The start of the range, included.
            end_timestamp (int): The end of the range, not included.
            worker_id (str): The id of the calculation holding the metrics refresh, heartbeated with every batch.

        Returns:
            Optional[Tuple[Dict[date, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]]: The legacy runs by the UTC
                day they were created on, and by their id. None when the metrics refresh was taken over.
        """
        keys = get_all_keys_for_table(
            redis_client=self.redis_client, prefix=self.db_prefix, table_type="sessions", count=METRICS_SCAN_COUNT
        )
        legacy_runs_by_day: Dict[date, List[Dict[str, Any]]] = {}
        legacy_runs_by_id: Dict[str, Dict[str, Any]] = {}
        for batch_start in range(0, len(keys), METRICS_BATCH_SIZE):
            if not self._heartbeat_metrics_refresh(worker_id):
                return None
            pipeline = self.redis_client.pipeline(transaction=False)
            for key in keys[batch_start : batch_start + METRICS_BATCH_SIZE]:
                pipeline.get(key)
            legacy_runs: List[Dict[str, Any]] = []
            for data in pipeline.execute():
                if not data:
                    continue
                session = deserialize_data(data)
                created_at = session.get("created_at") or 0
                # A session holds runs created after it started and before it was last written
                if created_at >= end_timestamp or (session.get("updated_at") or created_at) < start_timestamp:
                    continue
                legacy_runs.extend(
                    legacy_run
                    for legacy_run in build_component_metrics_legacy_runs(session)
                    if start_timestamp <= (legacy_run["created_at"] or 0) < end_timestamp
                )
            # The runs table wins on a run in both, as merge_runs_table_with_legacy_blob does
            pipeline = self.redis_client.pipeline(transaction=False)
            for legacy_run in legacy_runs:
                pipeline.exists(
                    generate_redis_key(prefix=self.db_prefix, table_type="runs", key_id=legacy_run["run_id"])
                )
            for legacy_run, exists in zip(legacy_runs, pipeline.execute()):
                if exists:
                    continue
                legacy_run_day = datetime.fromtimestamp(legacy_run["created_at"], tz=timezone.utc).date()
                legacy_runs_by_day.setdefault(legacy_run_day, []).append(legacy_run)
                legacy_runs_by_id[legacy_run["run_id"]] = legacy_run
        return legacy_runs_by_day, legacy_runs_by_id

    def _get_metrics_day_records(
        self,
        table_type: str,
        date_to_process: date,
        build_record: Callable[[Dict[str, Any]], Dict[str, Any]],
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Get the sessions or runs created on the given day, from the sorted set that lists them by created_at, each
        reduced with build_record before the next batch is read. None when should_stop returned True between
        batches."""
        start_timestamp = metrics_day_start(date_to_process)
        record_ids = self.redis_client.zrangebyscore(
            generate_created_at_index_key(self.db_prefix, table_type),
            start_timestamp,
            f"({metrics_day_start(date_to_process + timedelta(days=1))}",
        )
        records: List[Dict[str, Any]] = []
        for batch_start in range(0, len(record_ids), METRICS_BATCH_SIZE):  # type: ignore[arg-type]
            # Checked between batches too, so a stop never waits for the whole of a large day
            if should_stop is not None and should_stop():
                return None
            pipeline = self.redis_client.pipeline(transaction=False)
            for record_id in record_ids[batch_start : batch_start + METRICS_BATCH_SIZE]:  # type: ignore[index]
                record_id = record_id.decode() if isinstance(record_id, bytes) else str(record_id)
                pipeline.get(generate_redis_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id))
            records.extend(build_record(deserialize_data(data)) for data in pipeline.execute() if data)
        return records

    def _get_metrics_team_runs(
        self, team_session_ids: Set[str], end_timestamp: int, should_stop: Optional[Callable[[], bool]] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Get the runs of the given team sessions created in the day before end_timestamp, from the sorted set that
        lists the runs by created_at, a batch at a time. None when should_stop returned True between batches."""
        run_ids = self.redis_client.zrangebyscore(
            generate_created_at_index_key(self.db_prefix, "runs"), end_timestamp - 86400, f"({end_timestamp}"
        )
        team_runs: List[Dict[str, Any]] = []
        for batch_start in range(0, len(run_ids), METRICS_BATCH_SIZE):  # type: ignore[arg-type]
            if should_stop is not None and should_stop():
                return None
            pipeline = self.redis_client.pipeline(transaction=False)
            for run_id in run_ids[batch_start : batch_start + METRICS_BATCH_SIZE]:  # type: ignore[index]
                run_id = run_id.decode() if isinstance(run_id, bytes) else str(run_id)
                pipeline.get(generate_redis_key(prefix=self.db_prefix, table_type="runs", key_id=run_id))
            team_runs.extend(
                build_component_metrics_run(run)
                for run in (deserialize_data(data) for data in pipeline.execute() if data)
                if run.get("session_id") in team_session_ids
            )
        return team_runs

    def _get_metrics_parent_runs(self, parent_run_ids: List[str]) -> List[Dict[str, Any]]:
        """Get the stored runs that started the given runs, and the runs that started those, up to the whole run."""
        parent_runs: List[Dict[str, Any]] = []
        seen_run_ids: Set[str] = set()
        while parent_run_ids:
            seen_run_ids.update(parent_run_ids)
            for batch_start in range(0, len(parent_run_ids), METRICS_BATCH_SIZE):
                pipeline = self.redis_client.pipeline(transaction=False)
                for run_id in parent_run_ids[batch_start : batch_start + METRICS_BATCH_SIZE]:
                    pipeline.get(generate_redis_key(prefix=self.db_prefix, table_type="runs", key_id=run_id))
                parent_runs.extend(
                    build_component_metrics_run(deserialize_data(data)) for data in pipeline.execute() if data
                )
            parent_run_ids = sorted(
                {run["parent_run_id"] for run in parent_runs if run.get("parent_run_id")} - seen_run_ids
            )
        return parent_runs

    def _write_metrics_rows(self, worker_id: str, write: Callable[[Any], None]) -> bool:
        """Run the given writes of metrics rows in one transaction, only while this worker still holds the metrics
        refresh. False when another process took it over, and nothing was written.

        The row of the metrics refreshes table is watched, as _q_fenced_update watches a job, so a takeover between
        the check and the writes fails the transaction.

        Args:
            worker_id (str): The id of the calculation that holds the metrics refresh.
            write (Callable[[Any], None]): Adds the writes to the transaction it is given.
        """
        from redis.exceptions import WatchError

        refresh_key = self._metrics_refresh_key()
        for _ in range(10):
            try:
                with self.redis_client.pipeline(transaction=True) as pipe:
                    pipe.watch(refresh_key)
                    raw = pipe.get(refresh_key)
                    refresh_row = json.loads(raw if isinstance(raw, str) else raw.decode()) if raw is not None else {}
                    if refresh_row.get("locked_by") != worker_id:
                        pipe.unwatch()
                        return False
                    pipe.multi()
                    write(pipe)
                    pipe.execute()
                    return True
            except WatchError:
                continue  # the refresh changed under us; re-read and re-check
        return False

    def _write_user_metrics_rows(
        self, user_metrics_rows: List[Dict[str, Any]], rows_changed: bool, read_version: Optional[int], worker_id: str
    ) -> bool:
        """Write a period's rows of the user metrics table, from build_user_metrics_rows: the user rows, then the
        everyone row, which is completed only while it still has the version read before the period's rows. False when
        another process took the metrics refresh over, and nothing more was written."""
        period, period_date = user_metrics_rows[0]["aggregation_period"], user_metrics_rows[0]["date"]
        stored_rows = self._get_user_metrics_records(
            [
                record_id
                for record_id in self._get_metrics_record_ids("user_metrics", "date", [period_date.isoformat()])
                if metrics_record_key(record_id)[1] == period
            ]
        )
        everyone_row, changed_rows, stale_user_ids = user_metrics_rows_to_write(
            user_metrics_rows, stored_rows, rows_changed
        )
        stored_by_user = {row["user_id"]: row for row in stored_rows}
        stale_rows = [stored_by_user[user_id] for user_id in stale_user_ids]
        for batch_start in range(0, max(len(stale_rows), len(changed_rows)), METRICS_BATCH_SIZE):
            if not self._write_metrics_rows(
                worker_id,
                partial(
                    delete_user_metrics_rows,
                    prefix=self._metrics_prefix(),
                    user_metrics_rows=stale_rows[batch_start : batch_start + METRICS_BATCH_SIZE],
                ),
            ) or not self._write_metrics_rows(
                worker_id,
                partial(
                    bulk_upsert_user_metrics_rows,
                    prefix=self._metrics_prefix(),
                    user_metrics_rows=changed_rows[batch_start : batch_start + METRICS_BATCH_SIZE],
                    expire=self.expire,
                ),
            ):
                return False

        # Written last, so its version never moves without the rows it tells of
        if everyone_row is not None:
            return upsert_user_metrics_row(
                self.redis_client, self._metrics_prefix(), everyone_row, read_version, worker_id, self.expire
            )
        return True

    def _calculate_date_metrics(
        self,
        date_to_process: date,
        legacy_runs: List[Dict[str, Any]],
        legacy_runs_by_id: Dict[str, Dict[str, Any]],
        worker_id: str,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Rebuild one day's component and user metrics rows. False when nothing was written."""
        # Read before the day's runs, so a run written while they are read moves it
        read_version = self._get_user_metrics_version("daily", date_to_process)

        sessions = self._get_metrics_day_records(
            "sessions", date_to_process, build_component_metrics_session, should_stop
        )
        run_rows = self._get_metrics_day_records("runs", date_to_process, build_component_metrics_run, should_stop)
        if sessions is None or run_rows is None:
            return False
        # A legacy run migrated to the runs table since the legacy runs were read is among the day's runs, and is
        # counted from there
        day_run_ids = {run["run_id"] for run in run_rows}
        runs = run_rows + [run for run in legacy_runs if run["run_id"] not in day_run_ids]
        nested_run_ids = metrics_nested_run_ids(runs)

        # A run started by a run of another day, such as a member run after midnight, names that run's agent, team or
        # workflow as its parent, read from the legacy runs of the rebuild or the runs table
        day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
        parent_run_ids = sorted({run["parent_run_id"] for run in runs if run.get("parent_run_id")} - day_run_ids)
        parent_runs = [legacy_runs_by_id[run_id] for run_id in parent_run_ids if run_id in legacy_runs_by_id]
        parent_run_ids = [run_id for run_id in parent_run_ids if run_id not in legacy_runs_by_id]
        # A nested run also stored as a legacy run of its own is counted from that run, whatever day it is on
        stored_run_ids: Set[str] = {run_id for run_id in nested_run_ids if run_id in legacy_runs_by_id}

        # A nested run also stored as a run of its own is counted from that record, whatever day it is on
        run_ids = sorted(nested_run_ids)
        for batch_start in range(0, len(run_ids), METRICS_BATCH_SIZE):
            batch_run_ids = run_ids[batch_start : batch_start + METRICS_BATCH_SIZE]
            pipeline = self.redis_client.pipeline(transaction=False)
            for run_id in batch_run_ids:
                pipeline.exists(generate_redis_key(prefix=self.db_prefix, table_type="runs", key_id=run_id))
            stored_run_ids.update(run_id for run_id, exists in zip(batch_run_ids, pipeline.execute()) if exists)

        # A remote member's run after midnight is named by its team's run of the day before
        team_session_ids = metrics_remote_member_team_session_ids(runs)
        if team_session_ids:
            team_runs = self._get_metrics_team_runs(team_session_ids, metrics_day_start(date_to_process), should_stop)
            if team_runs is None:
                return False
            parent_runs.extend(team_runs)
            parent_run_ids.extend(run["parent_run_id"] for run in team_runs if run.get("parent_run_id"))

        parent_runs.extend(self._get_metrics_parent_runs(parent_run_ids))

        records = calculate_date_component_metrics(date_to_process, sessions, runs, stored_run_ids, parent_runs)
        stored_rows = self._get_component_metrics_records(
            self._get_metrics_record_ids("component_metrics", "date", [date_to_process.isoformat()])
        )

        # Heartbeated right before the day's writes, so a process whose lock went stale never overwrites the rows of
        # the process that took the refresh over
        if not self._heartbeat_metrics_refresh(worker_id):
            return False
        changed_rows, stale_keys = component_metrics_rows_to_write(records, stored_rows)
        stored_by_key = get_metrics_rows_by_key(stored_rows, COMPONENT_METRICS_KEY_COLUMNS[2:])
        stale_rows = [stored_by_key[stale_key] for stale_key in stale_keys]
        # created_at is never overwritten
        changed_rows = [
            {**row, "created_at": stored_row["created_at"]}
            if (stored_row := stored_by_key.get(tuple(row[column] for column in COMPONENT_METRICS_KEY_COLUMNS[2:])))
            else row
            for row in changed_rows
        ]
        # Each batch is written only while this worker still holds the refresh, so a process whose lock went stale
        # never overwrites the rows of the process that took the refresh over
        for batch_start in range(0, max(len(stale_rows), len(changed_rows)), METRICS_BATCH_SIZE):
            if not self._write_metrics_rows(
                worker_id,
                partial(
                    delete_component_metrics,
                    prefix=self._metrics_prefix(),
                    component_metrics_records=stale_rows[batch_start : batch_start + METRICS_BATCH_SIZE],
                ),
            ) or not self._write_metrics_rows(
                worker_id,
                partial(
                    bulk_upsert_component_metrics,
                    prefix=self._metrics_prefix(),
                    component_metrics_records=changed_rows[batch_start : batch_start + METRICS_BATCH_SIZE],
                    expire=self.expire,
                ),
            ):
                return False

        # Written after the component rows, so its version never moves without the rows it tells of
        if not self._write_user_metrics_rows(
            build_user_metrics_rows(records, "daily", date_to_process, metrics_day_completed(date_to_process)),
            rows_changed=bool(changed_rows or stale_keys),
            read_version=read_version,
            worker_id=worker_id,
        ):
            return False
        if changed_rows or stale_keys:
            # Reopened with the day, so a calculation that stops before its months leaves the month for the next
            return self._write_metrics_rows(
                worker_id,
                partial(
                    reopen_metrics_month,
                    prefix=self._metrics_prefix(),
                    month_start=date_to_process.replace(day=1),
                    expire=self.expire,
                ),
            )
        return True

    def _calculate_month_metrics(self, month_start: date, worker_id: str) -> bool:
        """Rebuild the month rows of the user metrics table from the component metrics rows of the month's days. False
        when another process took the refresh over, and nothing was written."""
        read_version = self._get_user_metrics_version("monthly", month_start)
        month_days = [
            month_start + timedelta(days=offset)
            for offset in range((metrics_month_end(month_start) - month_start).days + 1)
        ]
        record_ids = self._get_metrics_record_ids("component_metrics", "date", [day.isoformat() for day in month_days])
        # Added up a batch at a time, so a month of many rows is never held whole
        per_owner: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
        for batch_start in range(0, len(record_ids), METRICS_BATCH_SIZE):
            add_metrics_month_totals(
                per_owner,
                self._get_component_metrics_records(record_ids[batch_start : batch_start + METRICS_BATCH_SIZE]),
            )

        # Heartbeated right before the month's writes, so a process whose lock went stale never overwrites the rows
        # of the process that took the refresh over
        if not self._heartbeat_metrics_refresh(worker_id):
            return False
        # Added up per owner and component over the month, so a user of several days is one user of the month
        return self._write_user_metrics_rows(
            build_user_metrics_month_rows(month_start, per_owner),
            rows_changed=False,
            read_version=read_version,
            worker_id=worker_id,
        )

    def calculate_metrics(self, rebuild_from: Optional[date] = None) -> Optional[list[dict]]:
        """Calculate metrics for every day that changed since the last calculation.

        One process calculates at a time, whichever process or replica it runs in: the others return at once,
        having read nothing.

        Args:
            rebuild_from (Optional[date]): Also rebuild every day from this date to today, as after a release that
                changed how metrics are counted.

        Returns:
            Optional[list[dict]]: The metrics of the days calculated, or of today when nothing changed, as get_metrics
                returns them. None when another process is calculating them.

        Raises:
            Exception: If any error occurs while calculating the metrics.
        """
        try:
            calculated_dates = self.calculate_metrics_dates(rebuild_from=rebuild_from)
            if calculated_dates is None:
                return None
            if not calculated_dates:
                # Nothing changed: today's metrics come back, as they did when every refresh calculated today
                calculated_dates = [datetime.now(timezone.utc).date()]
            metrics, _ = self._get_metrics_rows(calculated_dates[0], calculated_dates[-1], None)
            return [metric for metric in metrics if metric["date"] in calculated_dates]

        except Exception as e:
            log_error(f"Error calculating metrics: {str(e)}")
            raise e

    def calculate_metrics_dates(
        self, should_stop: Optional[Callable[[], bool]] = None, rebuild_from: Optional[date] = None
    ) -> Optional[List[date]]:
        """Calculate metrics for every day that changed since the last calculation, as calculate_metrics does,
        without reading back the metrics of those days.

        Args:
            should_stop (Optional[Callable[[], bool]]): Checked before each day and month, and between a day's
                batches. Once it returns True, the calculation releases the refresh and stops; the next one continues
                from the first day still open.
            rebuild_from (Optional[date]): Also rebuild every day from this date to today.

        Returns:
            Optional[List[date]]: The days calculated, oldest first. None when another process is calculating them.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        if rebuild_from is not None:
            started_at = finished_at = None
            try:
                # A calculation that starts or finishes after this read keeps its own status
                stored_row = self._get_metrics_refresh_row()[0]
                if stored_row is not None:
                    started_at, finished_at = stored_row.get("started_at"), stored_row.get("finished_at")
                # Reopened as a write reopens a day, before the claim, so a calculation another process is running
                # leaves them to the next one
                everyone_record_ids = self._get_metrics_everyone_record_ids()
                for batch_start in range(0, len(everyone_record_ids), METRICS_BATCH_SIZE):
                    pipe = self.redis_client.pipeline()
                    reopen_metrics_days_from(
                        pipe,
                        self._metrics_prefix(),
                        everyone_record_ids[batch_start : batch_start + METRICS_BATCH_SIZE],
                        rebuild_from,
                        self.expire,
                    )
                    pipe.execute()
                # Yesterday and today are picked by the fingerprint, so it is marked for the next one too
                if not self._mark_metrics_refresh_rebuild():
                    return None
            except Exception as e:
                # Failed before the claim, so the refresh status shows it
                self._release_metrics_refresh(
                    None, error=database_error_message(e), started_at=started_at, finished_at=finished_at
                )
                raise

        worker_id = str(uuid4())
        # Claimed before anything is read, so a process that finds another calculating reads nothing
        refresh_row = self._claim_metrics_refresh(worker_id)
        if refresh_row is None:
            return None

        try:
            index_state = self._get_metrics_index_state(worker_id, force=rebuild_from is not None)
            if index_state is None:
                return None
            dates_to_process, fingerprint = self._get_metrics_dates_to_calculate(refresh_row, rebuild_from)
            if rebuild_from is not None:
                # Yesterday and today are picked by their fingerprint, not by being open
                today = datetime.now(timezone.utc).date()
                dates_to_process = sorted(
                    set(dates_to_process) | {day for day in [today - timedelta(days=1), today] if day >= rebuild_from}
                )

            legacy_runs_by_day: Dict[date, List[Dict[str, Any]]] = {}
            legacy_runs_by_id: Dict[str, Dict[str, Any]] = {}
            # Read once for every day until the v3.0.0 migration is stamped: no index finds one day's legacy runs
            # Redis stamps no version until the migration runs, so they are read only when a session held some
            if (
                dates_to_process
                and index_state["legacy_runs"]
                and packaging_version.parse(self.get_latest_schema_version(self.session_table_name) or "2.0.0")
                < packaging_version.parse("3.0.0")
            ):
                legacy_runs = self._get_metrics_legacy_runs(
                    metrics_day_start(dates_to_process[0]),
                    metrics_day_start(dates_to_process[-1] + timedelta(days=1)),
                    worker_id,
                )
                if legacy_runs is None:
                    return None
                legacy_runs_by_day, legacy_runs_by_id = legacy_runs
                # A legacy run is dated on its own day, which may hold no session or run of the tables
                today = datetime.now(timezone.utc).date()
                dates_to_process = sorted(
                    set(dates_to_process)
                    | {
                        day
                        for day in legacy_runs_by_day
                        if day <= today
                        and (refresh_row["finished_at"] is None or (rebuild_from is not None and day >= rebuild_from))
                    }
                )

            calculated_dates: List[date] = []
            for date_to_process in dates_to_process:
                if should_stop is not None and should_stop():
                    self._release_metrics_refresh(worker_id, stopped=True)
                    return None
                if not self._calculate_date_metrics(
                    date_to_process,
                    legacy_runs_by_day.get(date_to_process, []),
                    legacy_runs_by_id,
                    worker_id,
                    should_stop,
                ):
                    if should_stop is not None and should_stop():
                        self._release_metrics_refresh(worker_id, stopped=True)
                    return None
                calculated_dates.append(date_to_process)

            # A month row is read only once completed, so a month is built only once its last day can be completed
            month_starts = sorted(
                month_start
                for month_start in set(get_months_to_calculate_metrics_for(calculated_dates))
                | set(self._get_open_metrics_months())
                if metrics_day_completed(metrics_month_end(month_start))
            )
            for month_start in month_starts:
                if should_stop is not None and should_stop():
                    self._release_metrics_refresh(worker_id, stopped=True)
                    return None
                if not self._calculate_month_metrics(month_start, worker_id):
                    return None

        except Exception as e:
            self._release_metrics_refresh(worker_id, error=database_error_message(e))
            raise

        self._release_metrics_refresh(
            worker_id, fingerprint=fingerprint, claimed_fingerprint=refresh_row["fingerprint"]
        )

        if not calculated_dates:
            log_info("Metrics already calculated for all relevant dates.")
            return []

        log_debug("Updated metrics calculations")
        return calculated_dates

    def stop_metrics_refresh_on_read(self) -> None:
        """Stop calculating metrics before a read, for a database whose metrics are calculated in the background."""
        self._metrics_refreshed_at = float("inf")

    def _get_metrics_by_owner(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of each user and day from the component metrics, in the shape of the metrics table."""
        if user_id is None:
            record_ids = self._get_metrics_records_of_days("component_metrics", starting_date, ending_date)
        else:
            record_ids = [
                record_id
                for record_id in self._get_metrics_record_ids("component_metrics", "user_id", [user_id])
                if (starting_date is None or metrics_record_key(record_id)[0] >= starting_date)
                and (ending_date is None or metrics_record_key(record_id)[0] <= ending_date)
            ]
        rows = self._get_component_metrics_records(record_ids)
        if not rows:
            return [], None

        latest_updated_at = max((row["updated_at"] for row in rows if row.get("updated_at") is not None), default=None)
        return build_metrics_by_owner_from_rows(rows), latest_updated_at

    def _get_user_metrics_rows(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the day rows of the user metrics table in the shape of the metrics table: the everyone rows for ``""``, one
        user's rows for a name, and every user's rows for ``None``."""
        if user_id is None:
            record_ids = self._get_metrics_records_of_days("user_metrics", starting_date, ending_date)
        else:
            record_ids = [
                record_id
                for record_id in self._get_metrics_record_ids("user_metrics", "user_id", [user_id])
                if metrics_record_key(record_id)[1] == "daily"
                and (starting_date is None or metrics_record_key(record_id)[0] >= starting_date)
                and (ending_date is None or metrics_record_key(record_id)[0] <= ending_date)
            ]
        rows = sorted(
            (
                row
                for row in self._get_user_metrics_records(record_ids)
                if (user_id is not None or row["user_id"])
                # A day without sessions or runs keeps an everyone row of zeros, where agno_metrics kept no row
                and any(row[column] for column in USER_METRICS_COUNT_COLUMNS if column != "users_count")
            ),
            key=lambda row: (row["date"], row["user_id"]),
        )
        if not rows:
            return [], None

        # Get the latest updated_at, scoped to the same user filter. Every user's rows of a day are written with its
        # everyone row, so the everyone rows stand for them
        updated_at_ids = [
            record_id
            for record_id in self._get_metrics_record_ids("user_metrics", "user_id", [user_id or ""])
            if metrics_record_key(record_id)[1] == "daily"
        ]
        latest_updated_at = max(
            (
                updated_at
                for updated_at in self._get_user_metrics_column(updated_at_ids, "updated_at")
                if updated_at is not None
            ),
            default=None,
        )
        return build_metrics_from_user_metrics(rows), latest_updated_at

    def _get_metrics_rows(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of each user and day, as get_metrics returns them once the first calculate_metrics has
        finished: a user's from that user's rows, the runs with no user from their component metrics rows."""
        if user_id == "":
            return self._get_metrics_by_owner(starting_date, ending_date, user_id)
        metrics, latest_updated_at = self._get_user_metrics_rows(starting_date, ending_date, user_id)
        if user_id is not None:
            return metrics, latest_updated_at

        unowned_metrics, unowned_updated_at = self._get_metrics_by_owner(starting_date, ending_date, "")
        latest_updated_at = max(
            (updated_at for updated_at in [latest_updated_at, unowned_updated_at] if updated_at is not None),
            default=None,
        )
        return sorted(metrics + unowned_metrics, key=lambda x: (x["date"], x["user_id"] or "")), latest_updated_at

    def _metrics_calculated(self) -> bool:
        """Whether the first calculate_metrics has finished, so reads take the metrics tables over agno_metrics."""
        refresh_row = self._get_metrics_refresh_row()[0]
        return refresh_row is not None and refresh_row["finished_at"] is not None

    def _refresh_metrics_before_read(self) -> None:
        """Calculate metrics before a read, at most once per minute per process, once a first calculate_metrics has
        finished and unless metrics calculation is turned off. Another process calculating them holds the metrics
        refresh, so the read goes on at once."""
        if time.time() - self._metrics_refreshed_at < 60:
            return
        # Stamp first so failed runs are throttled too instead of retried on every read
        self._metrics_refreshed_at = time.time()
        try:
            # A first build reads every run, so a read never waits for one: until it has finished, reads serve the
            # deprecated metrics table
            if not metrics_calculation_enabled() or not self._metrics_calculated():
                return
            self.calculate_metrics_dates()
        except Exception as e:
            log_warning(f"Could not refresh metrics before reading them: {str(e)}")

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range.

        Metrics are read from the user metrics and component metrics once the first calculate_metrics has finished,
        and from the deprecated metrics table until then. They are refreshed first, at most once per minute per
        process, unless stop_metrics_refresh_on_read was called.

        Args:
            starting_date (Optional[date]): The starting date to filter by.
            ending_date (Optional[date]): The ending date to filter by.
            user_id (Optional[str]): The ID of the user to filter by. When None, all buckets are returned.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the list of metrics and the latest updated_at.

        Raises:
            Exception: If any error occurs while getting the metrics.
        """
        try:
            self._refresh_metrics_before_read()
            if self._metrics_calculated():
                return self._get_metrics_rows(starting_date, ending_date, user_id)

            all_metrics = self._get_all_records("metrics")

            # Filter by date range
            if starting_date is not None or ending_date is not None:
                filtered_metrics = []
                for metric in all_metrics:
                    metric_date = metric_record_day(metric)
                    if metric_date is None:
                        continue
                    if starting_date is not None and metric_date < starting_date:
                        continue
                    if ending_date is not None and metric_date > ending_date:
                        continue
                    filtered_metrics.append(metric)
                all_metrics = filtered_metrics

            # Filter by user_id
            if user_id is not None:
                all_metrics = [m for m in all_metrics if m.get("user_id") == user_id]
            else:
                # Records written before ownership existed hold a whole day, and only an
                # unscoped read sees them: an owner filter excludes them already
                all_metrics = drop_legacy_metrics(all_metrics)

            # Get latest updated_at
            latest_updated_at = None
            if all_metrics:
                latest_updated_at = max(metric.get("updated_at", 0) for metric in all_metrics)

            # Map the sentinel empty-string user_id back to None
            cleaned: List[dict] = []
            for metric in all_metrics:
                row = dict(metric)
                if row.get("user_id") == "":
                    row["user_id"] = None
                cleaned.append(row)
            return cleaned, latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics: {str(e)}")
            raise e

    def get_metrics_by_date(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of every user, one row per day, matching the given date range.

        Read from the everyone rows of the user metrics table once the first calculate_metrics has finished, and from the
        deprecated metrics table until then. They are refreshed first, as get_metrics does.

        Args:
            starting_date (Optional[date]): The starting date to filter by.
            ending_date (Optional[date]): The ending date to filter by.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If any error occurs while getting the metrics.
        """
        try:
            self._refresh_metrics_before_read()
            if self._metrics_calculated():
                return self._get_user_metrics_rows(starting_date, ending_date, "")
            return super().get_metrics_by_date(starting_date, ending_date)

        except Exception as e:
            log_error(f"Error getting metrics: {str(e)}")
            raise e

    def get_metrics_refresh_status(self) -> Optional[Dict[str, Any]]:
        """Get the status of the most recent calculate_metrics, from the metrics refreshes table.

        Returns:
            Optional[Dict[str, Any]]: The status ('running', 'completed' or 'failed'), when it started and finished,
                and its error. None before the first calculation.

        Raises:
            Exception: If any error occurs while getting the status.
        """
        try:
            return metrics_refresh_status(*self._get_metrics_refresh_row())

        except Exception as e:
            log_error(f"Error getting metrics refresh status: {str(e)}")
            raise e

    def _get_component_metrics_totals_by_date(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str],
        fields: List[str],
        use_month_rows: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Total the component metrics of the given date range, every day from one period.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs
                with no user.
            fields (List[str]): The columns to total.
            use_month_rows (bool): Total a calendar month inside the date range from its month user metrics row, as one
                date.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each date, and when they were last updated.
        """
        # The component metrics keep day rows only, so the runs with no user are read day by day
        full_months = metrics_full_months(starting_date, ending_date) if use_month_rows and user_id != "" else []
        # Only a completed month's total row stands for its days; an open one, reopened by a day rebuilt since or
        # not yet built, is read from its days
        month_record_ids = [
            record_id
            for record_id in self._get_metrics_everyone_record_ids()
            if metrics_record_key(record_id)[1] == "monthly" and metrics_record_key(record_id)[0] in full_months
        ]
        month_starts = sorted(
            metrics_record_key(record_id)[0]
            for record_id, completed in zip(
                month_record_ids, self._get_user_metrics_column(month_record_ids, "completed")
            )
            if completed
        )

        # Every owner is read from the everyone rows and a user from the user's rows; the runs with no user have no
        # user metrics row of their own, so they are read from their component rows
        table_type = "component_metrics" if user_id == "" else "user_metrics"
        record_ids = []
        for record_id in self._get_metrics_record_ids(table_type, "user_id", [user_id or ""]):
            day, aggregation_period = metrics_record_key(record_id)
            if (
                aggregation_period == "daily"
                and starting_date <= day <= ending_date
                and day.replace(day=1) not in month_starts
            ) or (aggregation_period == "monthly" and day in month_starts):
                record_ids.append(record_id)
        if table_type == "component_metrics":
            rows = self._get_component_metrics_records(record_ids)
        else:
            rows = self._get_user_metrics_records(record_ids)
        return total_metrics_rows(rows, starting_date, ending_date, fields, month_starts=month_starts)

    def get_component_metrics(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Get the component metrics totals of each day in the given date range.

        For every owner, each day is read from its everyone row; for one owner, from its rows. A read never calculates
        them: calculate_metrics does.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs
                with no user.
            fields (Optional[List[str]]): The columns to total. ``None`` totals all.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each day, and when they were last updated.

        Raises:
            Exception: If any error occurs while getting the component metrics.
        """
        try:
            fields = resolve_metrics_fields(fields)
            metrics, latest_updated_at = self._get_component_metrics_totals_by_date(
                starting_date, ending_date, user_id, fields
            )
            return [list_metrics_totals_models(day_totals) for day_totals in metrics], latest_updated_at

        except Exception as e:
            log_error(f"Error getting component metrics: {str(e)}")
            raise e

    def get_metrics_totals(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], Optional[int]]:
        """Get the component metrics totals of the whole given date range.

        A calendar month inside the date range that has month rows is read from them, and every other day as
        get_component_metrics reads it.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs
                with no user.
            fields (Optional[List[str]]): The columns to total. ``None`` totals all.

        Returns:
            Tuple[Dict[str, Any], Optional[int]]: The totals of the date range, and when they were last updated.

        Raises:
            Exception: If any error occurs while getting the metrics totals.
        """
        try:
            fields = resolve_metrics_fields(fields)
            totals, latest_updated_at = self._get_component_metrics_totals_by_date(
                starting_date, ending_date, user_id, fields, use_month_rows=True
            )
            return list_metrics_totals_models(merge_metrics_totals(totals, fields)), latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics totals: {str(e)}")
            raise e

    def get_metrics_versions(self, starting_date: date, ending_date: date) -> Optional[Dict[str, int]]:
        """Get the version of every everyone row of a day or a month of the user metrics in the given date range.

        Metrics are refreshed first, as get_metrics refreshes them.

        Args:
            starting_date (date): The first day of the date range.
            ending_date (date): The last day of the date range.

        Returns:
            Optional[Dict[str, int]]: The version of each everyone row, keyed by its aggregation period and date. The
                same again only while no calculation wrote a row of the date range. ``None`` until the first
                calculate_metrics has finished: a read would find no rows to total.

        Raises:
            Exception: If any error occurs while getting the metrics versions.
        """
        try:
            self._refresh_metrics_before_read()
            if not self._metrics_calculated():
                return None

            # Read off the index by user, so a long date range reads only the everyone rows that exist. A month's row
            # is dated its first day
            record_ids = [
                record_id
                for record_id in self._get_metrics_everyone_record_ids()
                if starting_date <= metrics_record_key(record_id)[0] <= ending_date
            ]
            return metrics_versions(
                [
                    SimpleNamespace(
                        aggregation_period=metrics_record_key(record_id)[1],
                        date=metrics_record_key(record_id)[0],
                        version=version,
                    )
                    for record_id, version in zip(record_ids, self._get_user_metrics_column(record_ids, "version"))
                    if version is not None
                ]
            )

        except Exception as e:
            log_error(f"Error getting metrics versions: {str(e)}")
            raise e

    # -- Knowledge methods --

    @staticmethod
    def _knowledge_doc_is_visible(doc: Dict[str, Any], user_id: Optional[str]) -> bool:
        """Whether the given knowledge row is owned by ``user_id`` or unowned. Unscoped callers see everything."""
        if user_id is None:
            return True
        owner = doc.get("user_id")
        return owner is None or owner == user_id

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): The ID of the user. If provided, only deletes the row if it belongs to this user.

        Raises:
            Exception: If any error occurs while deleting the knowledge content.
        """
        try:
            if user_id is not None:
                existing = self._get_record("knowledge", id)
                if existing is None or existing.get("user_id") != user_id:
                    log_debug(f"Skipping delete of knowledge content {id}: not owned by {user_id}")
                    return
            self._delete_record("knowledge", id)

        except Exception as e:
            log_error(f"Error deleting knowledge content: {str(e)}")
            raise e

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): The ID of the user. If provided, only returns rows owned by this user or unowned.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If any error occurs while getting the knowledge content.
        """
        try:
            document_raw = self._get_record("knowledge", id)
            if document_raw is None:
                return None
            if not self._knowledge_doc_is_visible(document_raw, user_id):
                return None

            return KnowledgeRow.model_validate(document_raw)

        except Exception as e:
            log_error(f"Error getting knowledge content: {str(e)}")
            raise e

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).
            user_id (Optional[str]): The ID of the user. If provided, only returns rows owned by this user or unowned.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If any error occurs while getting the knowledge contents.
        """
        try:
            all_documents = self._get_all_records("knowledge")
            if len(all_documents) == 0:
                return [], 0

            # Apply linked_to filter if provided
            if linked_to is not None:
                all_documents = [doc for doc in all_documents if doc.get("linked_to") == linked_to]

            # Apply owner filter if provided
            if user_id is not None:
                all_documents = [doc for doc in all_documents if self._knowledge_doc_is_visible(doc, user_id)]

            total_count = len(all_documents)

            # Apply sorting
            sorted_documents = apply_sorting(records=all_documents, sort_by=sort_by, sort_order=sort_order)

            # Apply pagination
            paginated_documents = apply_pagination(records=sorted_documents, limit=limit, page=page)

            return [KnowledgeRow.model_validate(doc) for doc in paginated_documents], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {str(e)}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.

        Raises:
            Exception: If any error occurs while upserting the knowledge content.
        """
        try:
            # A scoped write must not overwrite a record it does not own
            if knowledge_row.user_id is not None and knowledge_row.id:
                stored = self._get_record("knowledge", knowledge_row.id)
                if stored is not None and stored.get("user_id") != knowledge_row.user_id:
                    raise ValueError(f"Knowledge content {knowledge_row.id} not found")

            data = knowledge_row.model_dump()
            success = self._store_record("knowledge", knowledge_row.id, data)  # type: ignore

            return knowledge_row if success else None

        except Exception as e:
            log_error(f"Error upserting knowledge content: {str(e)}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in Redis.

        Args:
            eval_run (EvalRunRecord): The eval run to create.

        Returns:
            Optional[EvalRunRecord]: The created eval run if successful, None otherwise.

        Raises:
            Exception: If any error occurs while creating the eval run.
        """
        try:
            current_time = int(time.time())
            data = {"created_at": current_time, "updated_at": current_time, **eval_run.model_dump()}

            success = self._store_record(
                "evals",
                eval_run.run_id,
                data,
                index_fields=["agent_id", "team_id", "workflow_id", "model_id", "eval_type"],
            )

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run if success else None

        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            raise e

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from Redis.

        Args:
            eval_run_id (str): The ID of the eval run to delete.

        Raises:
            Exception: If any error occurs while deleting the eval run.
        """
        try:
            if self._delete_record(
                "evals", eval_run_id, index_fields=["agent_id", "team_id", "workflow_id", "model_id", "eval_type"]
            ):
                log_debug(f"Deleted eval run with ID: {eval_run_id}")
            else:
                log_debug(f"No eval run found with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {str(e)}")
            raise

    def delete_eval_runs(self, eval_run_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple eval runs from Redis.

        Args:
            eval_run_ids (List[str]): The IDs of the eval runs to delete.
            user_id (Optional[str]): If set, only delete runs owned by this user.

        Raises:
            Exception: If any error occurs while deleting the eval runs.
        """
        try:
            deleted_count = 0
            for eval_run_id in eval_run_ids:
                if user_id is not None:
                    existing = self._get_record("evals", eval_run_id)
                    if existing is None or existing.get("user_id") != user_id:
                        continue
                if self._delete_record(
                    "evals", eval_run_id, index_fields=["agent_id", "team_id", "workflow_id", "model_id", "eval_type"]
                ):
                    deleted_count += 1

            if deleted_count == 0:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_debug(f"Deleted {deleted_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")
            raise

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from Redis.

        Args:
            eval_run_id (str): The ID of the eval run to get.
            user_id (Optional[str]): If set, only return the run if owned by this user.

        Returns:
            Optional[EvalRunRecord]: The eval run if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the eval run.
        """
        try:
            eval_run_raw = self._get_record("evals", eval_run_id)
            if eval_run_raw is None:
                return None

            if user_id is not None and eval_run_raw.get("user_id") != user_id:
                return None

            if not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {str(e)}")
            raise e

    def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        filter_type: Optional[EvalFilterType] = None,
        eval_type: Optional[List[EvalType]] = None,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
        """Get all eval runs from Redis.

        Args:
            limit (Optional[int]): The maximum number of eval runs to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The order to sort by.

        Returns:
            List[EvalRunRecord]: The list of eval runs.

        Raises:
            Exception: If any error occurs while getting the eval runs.
        """
        try:
            all_eval_runs = self._get_all_records("evals")

            # Apply filters
            filtered_runs = []
            for run in all_eval_runs:
                # Agent/team/workflow filters
                if agent_id is not None and run.get("agent_id") != agent_id:
                    continue
                if team_id is not None and run.get("team_id") != team_id:
                    continue
                if workflow_id is not None and run.get("workflow_id") != workflow_id:
                    continue
                if model_id is not None and run.get("model_id") != model_id:
                    continue
                if user_id is not None and run.get("user_id") != user_id:
                    continue

                # Eval type filter
                if eval_type is not None and len(eval_type) > 0:
                    if run.get("eval_type") not in eval_type:
                        continue

                # Filter type
                if filter_type is not None:
                    if filter_type == EvalFilterType.AGENT and run.get("agent_id") is None:
                        continue
                    elif filter_type == EvalFilterType.TEAM and run.get("team_id") is None:
                        continue
                    elif filter_type == EvalFilterType.WORKFLOW and run.get("workflow_id") is None:
                        continue

                filtered_runs.append(run)

            if sort_by is None:
                sort_by = "created_at"
                sort_order = "desc"

            sorted_runs = apply_sorting(records=filtered_runs, sort_by=sort_by, sort_order=sort_order)
            paginated_runs = apply_pagination(records=sorted_runs, limit=limit, page=page)

            if not deserialize:
                return paginated_runs, len(filtered_runs)

            return [EvalRunRecord.model_validate(row) for row in paginated_runs]

        except Exception as e:
            log_error(f"Exception getting eval runs: {str(e)}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Update the name of an eval run in Redis.

        Args:
            eval_run_id (str): The ID of the eval run to rename.
            name (str): The new name of the eval run.
            user_id (Optional[str]): If set, only rename the run if owned by this user.

        Returns:
            Optional[Dict[str, Any]]: The updated eval run data if successful, None otherwise.

        Raises:
            Exception: If any error occurs while updating the eval run name.
        """
        try:
            eval_run_data = self._get_record("evals", eval_run_id)
            if eval_run_data is None:
                return None

            if user_id is not None and eval_run_data.get("user_id") != user_id:
                return None

            eval_run_data["name"] = name
            eval_run_data["updated_at"] = int(time.time())

            success = self._store_record("evals", eval_run_id, eval_run_data)
            if not success:
                return None

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not deserialize:
                return eval_run_data

            return EvalRunRecord.model_validate(eval_run_data)

        except Exception as e:
            log_error(f"Error updating eval run name {eval_run_id}: {str(e)}")
            raise

    def update_eval_run_user_id(self, eval_run_id: str, user_id: str) -> None:
        """Set the owner (user_id) on an existing eval run.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            user_id (str): The owner to set.
        """
        try:
            eval_run_data = self._get_record("evals", eval_run_id)
            if eval_run_data is None:
                return

            eval_run_data["user_id"] = user_id
            self._store_record("evals", eval_run_id, eval_run_data)

        except Exception as e:
            log_error(f"Error setting owner on eval run {eval_run_id}: {str(e)}")
            raise

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            # Check if trace already exists
            existing = self._get_record("traces", trace.trace_id)

            if existing:
                # workflow (level 3) > team (level 2) > agent (level 1) > child/unknown (level 0)
                def get_component_level(
                    workflow_id: Optional[str], team_id: Optional[str], agent_id: Optional[str], name: str
                ) -> int:
                    # Check if name indicates a root span
                    is_root_name = ".run" in name or ".arun" in name

                    if not is_root_name:
                        return 0  # Child span (not a root)
                    elif workflow_id:
                        return 3  # Workflow root
                    elif team_id:
                        return 2  # Team root
                    elif agent_id:
                        return 1  # Agent root
                    else:
                        return 0  # Unknown

                existing_level = get_component_level(
                    existing.get("workflow_id"),
                    existing.get("team_id"),
                    existing.get("agent_id"),
                    existing.get("name", ""),
                )
                new_level = get_component_level(trace.workflow_id, trace.team_id, trace.agent_id, trace.name)

                # Only update name if new trace is from a higher or equal level
                should_update_name = new_level > existing_level

                # Parse existing start_time to calculate correct duration
                existing_start_time_str = existing.get("start_time")
                if isinstance(existing_start_time_str, str):
                    existing_start_time = datetime.fromisoformat(existing_start_time_str.replace("Z", "+00:00"))
                else:
                    existing_start_time = trace.start_time

                recalculated_duration_ms = int((trace.end_time - existing_start_time).total_seconds() * 1000)

                # Update existing record
                existing["end_time"] = trace.end_time.isoformat()
                existing["duration_ms"] = recalculated_duration_ms
                existing["status"] = trace.status
                if should_update_name:
                    existing["name"] = trace.name

                # Preserve existing non-null context values: only fill in fields
                # that the existing row left blank. Otherwise a later upsert from
                # a child span (e.g. a post-hook agent's run with a different
                # session_id) would overwrite the trace's already-correct context.
                if existing.get("run_id") is None and trace.run_id is not None:
                    existing["run_id"] = trace.run_id
                if existing.get("session_id") is None and trace.session_id is not None:
                    existing["session_id"] = trace.session_id
                if existing.get("user_id") is None and trace.user_id is not None:
                    existing["user_id"] = trace.user_id
                if existing.get("agent_id") is None and trace.agent_id is not None:
                    existing["agent_id"] = trace.agent_id
                if existing.get("team_id") is None and trace.team_id is not None:
                    existing["team_id"] = trace.team_id
                if existing.get("workflow_id") is None and trace.workflow_id is not None:
                    existing["workflow_id"] = trace.workflow_id

                log_debug(
                    f"  Updating trace with context: run_id={existing.get('run_id', 'unchanged')}, "
                    f"session_id={existing.get('session_id', 'unchanged')}, "
                    f"user_id={existing.get('user_id', 'unchanged')}, "
                    f"agent_id={existing.get('agent_id', 'unchanged')}, "
                    f"team_id={existing.get('team_id', 'unchanged')}, "
                )

                self._store_record(
                    "traces",
                    trace.trace_id,
                    existing,
                    index_fields=["run_id", "session_id", "user_id", "agent_id", "team_id", "workflow_id", "status"],
                )
            else:
                trace_dict = trace.to_dict()
                trace_dict.pop("total_spans", None)
                trace_dict.pop("error_count", None)
                self._store_record(
                    "traces",
                    trace.trace_id,
                    trace_dict,
                    index_fields=["run_id", "session_id", "user_id", "agent_id", "team_id", "workflow_id", "status"],
                )

        except Exception as e:
            log_error(f"Error creating trace: {str(e)}")
            # Don't raise - tracing should not break the main application flow

    def get_trace(
        self,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ):
        """Get a single trace by trace_id or other filters.

        Args:
            trace_id: The unique trace identifier.
            run_id: Filter by run ID (returns first match).

        Returns:
            Optional[Trace]: The trace if found, None otherwise.

        Note:
            If multiple filters are provided, trace_id takes precedence.
            For other filters, the most recent trace is returned.
        """
        try:
            from agno.tracing.schemas import Trace as TraceSchema

            if trace_id:
                result = self._get_record("traces", trace_id)
                if result:
                    # Calculate total_spans and error_count
                    all_spans = self._get_all_records("spans")
                    trace_spans = [s for s in all_spans if s.get("trace_id") == trace_id]
                    result["total_spans"] = len(trace_spans)
                    result["error_count"] = len([s for s in trace_spans if s.get("status_code") == "ERROR"])
                    return TraceSchema.from_dict(result)
                return None

            elif run_id:
                all_traces = self._get_all_records("traces")
                matching = [t for t in all_traces if t.get("run_id") == run_id]
                if matching:
                    # Sort by start_time descending and get most recent
                    matching.sort(key=lambda x: x.get("start_time", ""), reverse=True)
                    result = matching[0]
                    # Calculate total_spans and error_count
                    all_spans = self._get_all_records("spans")
                    trace_spans = [s for s in all_spans if s.get("trace_id") == result.get("trace_id")]
                    result["total_spans"] = len(trace_spans)
                    result["error_count"] = len([s for s in trace_spans if s.get("status_code") == "ERROR"])
                    return TraceSchema.from_dict(result)
                return None

            else:
                log_debug("get_trace called without any filter parameters")
                return None

        except Exception as e:
            log_error(f"Error getting trace: {str(e)}")
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
    ) -> tuple[List, int]:
        """Get traces matching the provided filters.

        Args:
            run_id: Filter by run ID.
            session_id: Filter by session ID.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            status: Filter by status (OK, ERROR, UNSET).
            start_time: Filter traces starting after this datetime.
            end_time: Filter traces ending before this datetime.
            limit: Maximum number of traces to return per page.
            page: Page number (1-indexed).

        Returns:
            tuple[List[Trace], int]: Tuple of (list of matching traces, total count).
        """
        try:
            from agno.tracing.schemas import Trace as TraceSchema

            log_debug(
                f"get_traces called with filters: run_id={run_id}, session_id={session_id}, "
                f"user_id={user_id}, agent_id={agent_id}, page={page}, limit={limit}"
            )

            all_traces = self._get_all_records("traces")
            all_spans = self._get_all_records("spans")

            # Apply filters
            filtered_traces = []
            for trace in all_traces:
                if run_id and trace.get("run_id") != run_id:
                    continue
                if session_id and trace.get("session_id") != session_id:
                    continue
                if user_id and trace.get("user_id") != user_id:
                    continue
                if agent_id and trace.get("agent_id") != agent_id:
                    continue
                if team_id and trace.get("team_id") != team_id:
                    continue
                if workflow_id and trace.get("workflow_id") != workflow_id:
                    continue
                if status and trace.get("status") != status:
                    continue
                if start_time:
                    trace_start = trace.get("start_time", "")
                    if trace_start and trace_start < start_time.isoformat():
                        continue
                if end_time:
                    trace_end = trace.get("end_time", "")
                    if trace_end and trace_end > end_time.isoformat():
                        continue

                filtered_traces.append(trace)

            total_count = len(filtered_traces)

            # Sort by start_time descending
            filtered_traces.sort(key=lambda x: x.get("start_time", ""), reverse=True)

            # Apply pagination
            paginated_traces = apply_pagination(records=filtered_traces, limit=limit, page=page)

            traces = []
            for row in paginated_traces:
                # Calculate total_spans and error_count
                trace_spans = [s for s in all_spans if s.get("trace_id") == row.get("trace_id")]
                row["total_spans"] = len(trace_spans)
                row["error_count"] = len([s for s in trace_spans if s.get("status_code") == "ERROR"])
                traces.append(TraceSchema.from_dict(row))

            return traces, total_count

        except Exception as e:
            log_error(f"Error getting traces: {str(e)}")
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
        group_by: Literal["session", "agent", "team", "workflow", "endpoint"] = "session",
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get trace statistics grouped by session.

        Args:
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            start_time: Filter sessions with traces created after this datetime.
            end_time: Filter sessions with traces created before this datetime.
            limit: Maximum number of sessions to return per page.
            page: Page number (1-indexed).
            group_by: Only the default "session" grouping is supported by this backend.

        Returns:
            tuple[List[Dict], int]: Tuple of (list of session stats dicts, total count).
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                first_trace_at, last_trace_at.
        """
        if group_by != "session":
            raise NotImplementedError(
                f"get_trace_stats with group_by={group_by!r} is not supported by {self.__class__.__name__}. "
                "Only the default 'session' grouping is available."
            )

        try:
            log_debug(
                f"get_trace_stats called with filters: user_id={user_id}, agent_id={agent_id}, "
                f"workflow_id={workflow_id}, team_id={team_id}, "
                f"start_time={start_time}, end_time={end_time}, page={page}, limit={limit}"
            )

            all_traces = self._get_all_records("traces")

            # Filter traces and group by session_id
            session_stats: Dict[str, Dict[str, Any]] = {}
            for trace in all_traces:
                trace_session_id = trace.get("session_id")
                if not trace_session_id:
                    continue

                # Apply filters
                if user_id and trace.get("user_id") != user_id:
                    continue
                if agent_id and trace.get("agent_id") != agent_id:
                    continue
                if team_id and trace.get("team_id") != team_id:
                    continue
                if workflow_id and trace.get("workflow_id") != workflow_id:
                    continue

                created_at = trace.get("created_at", "")
                if start_time and created_at < start_time.isoformat():
                    continue
                if end_time and created_at > end_time.isoformat():
                    continue

                if trace_session_id not in session_stats:
                    session_stats[trace_session_id] = {
                        "session_id": trace_session_id,
                        "user_id": trace.get("user_id"),
                        "agent_id": trace.get("agent_id"),
                        "team_id": trace.get("team_id"),
                        "workflow_id": trace.get("workflow_id"),
                        "total_traces": 0,
                        "first_trace_at": created_at,
                        "last_trace_at": created_at,
                    }

                session_stats[trace_session_id]["total_traces"] += 1
                if created_at < session_stats[trace_session_id]["first_trace_at"]:
                    session_stats[trace_session_id]["first_trace_at"] = created_at
                if created_at > session_stats[trace_session_id]["last_trace_at"]:
                    session_stats[trace_session_id]["last_trace_at"] = created_at

            # Convert to list and sort by last_trace_at descending
            stats_list = list(session_stats.values())
            stats_list.sort(key=lambda x: x.get("last_trace_at", ""), reverse=True)

            total_count = len(stats_list)

            # Apply pagination
            paginated_stats = apply_pagination(records=stats_list, limit=limit, page=page)

            # Convert ISO strings to datetime objects
            for stat in paginated_stats:
                first_trace_at_str = stat["first_trace_at"]
                last_trace_at_str = stat["last_trace_at"]
                stat["first_trace_at"] = datetime.fromisoformat(first_trace_at_str.replace("Z", "+00:00"))
                stat["last_trace_at"] = datetime.fromisoformat(last_trace_at_str.replace("Z", "+00:00"))

            return paginated_stats, total_count

        except Exception as e:
            log_error(f"Error getting trace stats: {str(e)}")
            return [], 0

    # --- Spans ---
    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            self._store_record(
                "spans",
                span.span_id,
                span.to_dict(),
                index_fields=["trace_id", "parent_span_id"],
            )

        except Exception as e:
            log_error(f"Error creating span: {str(e)}")

    def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        if not spans:
            return

        try:
            for span in spans:
                self._store_record(
                    "spans",
                    span.span_id,
                    span.to_dict(),
                    index_fields=["trace_id", "parent_span_id"],
                )

        except Exception as e:
            log_error(f"Error creating spans batch: {str(e)}")

    def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        try:
            from agno.tracing.schemas import Span as SpanSchema

            result = self._get_record("spans", span_id)
            if result:
                return SpanSchema.from_dict(result)
            return None

        except Exception as e:
            log_error(f"Error getting span: {str(e)}")
            return None

    def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        """Get spans matching the provided filters.

        Args:
            trace_id: Filter by trace ID.
            parent_span_id: Filter by parent span ID.
            limit: Maximum number of spans to return.

        Returns:
            List[Span]: List of matching spans.
        """
        try:
            from agno.tracing.schemas import Span as SpanSchema

            all_spans = self._get_all_records("spans")

            # Apply filters
            filtered_spans = []
            for span in all_spans:
                if trace_id and span.get("trace_id") != trace_id:
                    continue
                if parent_span_id and span.get("parent_span_id") != parent_span_id:
                    continue
                filtered_spans.append(span)

            # Apply limit
            if limit:
                filtered_spans = filtered_spans[:limit]

            return [SpanSchema.from_dict(s) for s in filtered_spans]

        except Exception as e:
            log_error(f"Error getting spans: {str(e)}")
            return []

    # -- Learning methods (stubs) --
    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Learning methods not yet implemented for RedisDb")

    def upsert_learning(
        self,
        id: str,
        learning_type: str,
        content: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError("Learning methods not yet implemented for RedisDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for RedisDb")

    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("Learning methods not yet implemented for RedisDb")

    # -- Job queue (durable background runs) --------------------------------
    # The queue contract, matching the Postgres adapters method-for-method
    # (see agno.job_queue.store.InMemoryQueueStore for the reference). Sync,
    # like every other method on this adapter; the queue worker wraps sync
    # stores in a thread adapter. Claims and fenced writes use optimistic
    # WATCH/MULTI on the job key - the SKIP LOCKED equivalent.
    #
    # Durability caveat: Redis acceptance durability depends on persistence
    # configuration (use AOF appendfsync everysec/always for Postgres-grade
    # guarantees; default RDB snapshotting can lose recently accepted jobs).

    def _q_key(self, suffix: str) -> str:
        return f"{self.db_prefix}:jobs:{suffix}"

    def _q_job_key(self, job_id: str) -> str:
        return self._q_key(f"job:{job_id}")

    def _q_server_now(self) -> int:
        """Redis server time as an integer epoch, for LEASE math.

        Lease decisions must be anchored to ONE clock (the Postgres store
        anchors to the database's NOW() for exactly this reason). With
        worker wall clocks, a replica whose clock runs fast sees healthy
        leases as expired and sweeps live runs - and since the sweep steals
        the lock, the victim's own completion is fenced out and its run is
        reported failed despite having finished; with multi-attempt budgets
        that skew-triggered false sweep means duplicate side-effect
        execution. TIME is the Redis server's clock, identical for every
        worker on the shared store, so claim/heartbeat/sweep all agree.

        Not applied to queue_stats' age arithmetic or the retention
        cleanup cutoff; those only shift reporting/retention by the skew,
        never ownership (mirroring the Postgres store's scope).
        """
        seconds, _microseconds = self.redis_client.time()
        return int(seconds)

    def _q_idem_key(self, user_id: Optional[str], idempotency_key: str) -> str:
        """Collision-free dedup key for the (user, idempotency-key) tuple.

        The user segment is length-prefixed so the tuple boundary is
        unambiguous: (user="a", key="b:c") encodes to "u1:a:b:c" while
        (user="a:b", key="c") encodes to "u3:a:b:c" - a plain ':' join
        aliases both. Anonymous submits encode as "u0::{key}", which no
        literal user id (including "-") can produce."""
        user = user_id or ""
        return self._q_key(f"idem:u{len(user)}:{user}:{idempotency_key}")

    def _q_load_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        raw = self.redis_client.get(self._q_job_key(job_id))
        if raw is None:
            return None
        return json.loads(raw if isinstance(raw, str) else raw.decode())

    def _q_session_key(self, job: Dict[str, Any]) -> str:
        from hashlib import sha256

        from agno.job_queue.session import session_identity

        identity = json.dumps(session_identity(job), separators=(",", ":"))
        return self._q_key("session:" + sha256(identity.encode()).hexdigest())

    def _q_stamp_session_seq(self, pipe: Any, job: Dict[str, Any]) -> Dict[str, Any]:
        """Sequence a ticket entering its session index after every live ticket.

        The index holds exactly the live tickets, scored by sequence; watching it orders
        concurrent entries (submit, requeue) by the commit that wins."""
        from agno.job_queue.session import with_session_seq

        session_key = self._q_session_key(job)
        pipe.watch(session_key)
        top = pipe.zrevrange(session_key, 0, 0, withscores=True)
        return with_session_seq(job, int(top[0][1]) + 1 if top else 1)

    def _q_session_members(self, session_key: str) -> List[Dict[str, Any]]:
        """The live serialized tickets of a session, read outside any transaction (advisory)."""
        member_ids = [_q_to_str(value) for value in self.redis_client.zrange(session_key, 0, -1)]
        if not member_ids:
            return []
        raw = self.redis_client.mget([self._q_job_key(value) for value in member_ids])
        return [json.loads(value) for value in raw if value is not None]

    def _q_save_job_in_pipe(self, pipe: Any, job: Dict[str, Any]) -> None:
        from agno.job_queue.session import LIVE_STATUSES

        pipe.set(self._q_job_key(job["id"]), json.dumps(job))
        if (job.get("payload") or {}).get("serialize_session") is True:
            key = self._q_session_key(job)
            if job["status"] in LIVE_STATUSES:
                pipe.zadd(key, {job["id"]: job["payload"].get("session_seq") or 0})
            else:
                pipe.zrem(key, job["id"])

    def enqueue_job(self, job: Dict[str, Any], max_depth: int = 0) -> Dict[str, Any]:
        """Insert an accepted run job (idempotency-first, then depth gate).

        The idempotency key and the job document commit in ONE MULTI under
        WATCH: a crash can no longer leave a dangling key that 409-wedges the
        idempotency key until its TTL. A dangling key from a pre-fix crash is
        self-healed: a key whose job document is missing is treated as
        orphaned and taken over (WATCH arbitrates racing takeovers)."""
        from redis.exceptions import WatchError

        # Falsy ("" or None) means no dedup - matching the Postgres store, which
        # treats an empty header as no key (an "" key would otherwise wedge
        # every later empty-header submit onto one job). The STORED document
        # normalizes too (Postgres parity: the column reads NULL, never '')
        # so get_job consumers need no per-store knowledge.
        if not job.get("idempotency_key"):
            job = {**job, "idempotency_key": None}
        idem = job.get("idempotency_key")
        # user_id scopes the dedup namespace (cross-tenant key reuse must not
        # attach to another tenant's run) - mirrors the Postgres index
        idem_key = self._q_idem_key(job.get("user_id"), idem) if idem is not None else None

        job_key = self._q_job_key(job["id"])
        # Same-session submits also contend on the session index; every round commits one of them.
        attempts = 100 if (job.get("payload") or {}).get("serialize_session") is True else 10

        for _ in range(attempts):
            with self.redis_client.pipeline() as pipe:
                try:
                    # The job key is always WATCHed: the MULTI below SETs it,
                    # and a racing enqueue of the same id must not silently
                    # overwrite (see the existence check further down).
                    if idem_key is not None:
                        pipe.watch(job_key, idem_key)
                        existing_id = pipe.get(idem_key)
                        if existing_id is not None:
                            existing_id = existing_id if isinstance(existing_id, str) else existing_id.decode()
                            existing = self._q_load_job(existing_id)
                            if existing is not None and existing.get("user_id") == job.get("user_id"):
                                pipe.unwatch()
                                return {"accepted": False, "reason": "duplicate", "job": existing}
                            # Orphaned key (dual-write crash before this fix)
                            # OR a legacy/aliased key pointing at another
                            # tenant's job (defense-in-depth: a duplicate
                            # attach hands the caller that job's identifiers
                            # and live event stream) - never attach; fall
                            # through and take the key over inside the MULTI
                    else:
                        pipe.watch(job_key)

                    if max_depth and max_depth > 0:
                        queued = int(self.redis_client.zcard(self._q_key("queued")))
                        if queued >= max_depth:
                            pipe.unwatch()
                            return {"accepted": False, "reason": "queue_full", "job": None}

                    # Existing document under this id: mirror Postgres, where
                    # id is the primary key - a collision is a programming
                    # error (ids are server-minted uuid4), never a client
                    # dedup. Silently SETting would reset a live ticket to
                    # queued/attempt-0 - two executors, the first one's
                    # completion fenced out.
                    if pipe.exists(job_key):
                        pipe.unwatch()
                        raise RuntimeError(f"enqueue_job: job {job['id']} already exists; ids are never reused")

                    if (job.get("payload") or {}).get("serialize_session") is True:
                        job = self._q_stamp_session_seq(pipe, job)

                    pipe.multi()
                    if idem_key is not None:
                        pipe.set(idem_key, job["id"])
                    self._q_save_job_in_pipe(pipe, job)
                    pipe.zadd(self._q_key("queued"), {job["id"]: job["available_at"]})
                    pipe.zadd(self._q_key("all"), {job["id"]: job["created_at"]})
                    pipe.execute()
                    return {"accepted": True, "reason": None, "job": dict(job)}
                except WatchError:
                    continue  # another submitter raced this key; re-evaluate
        raise RuntimeError(f"enqueue_job: submit contention did not settle after {attempts} attempts")

    def claim_job(
        self, worker_id: str, lock_grace_seconds: int = 60, deployment_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Atomically claim the oldest executable job (queued, or stale-running
        within the attempt budget). WATCH/MULTI CAS; a raced claim moves on.
        Deployment affinity filters BOTH branches (a reclaim executes too):
        NULL rides anywhere, stamped jobs only on matching workers;
        deployment_id=None degenerates to claiming only unstamped jobs.

        The scan PAGES past affinity mismatches: a fixed window would let a
        head of foreign-deployment jobs starve matching jobs sitting behind
        them indefinitely (foreign entries stay queued at the front). Each
        page is pre-filtered with one pipelined MGET; the CAS inside
        _q_try_claim remains the only authority."""
        now = self._q_server_now()
        stale = now - lock_grace_seconds

        job = self._q_scan_claim(
            self._q_key("queued"), now, worker_id, now, expect_status="queued", deployment_id=deployment_id
        )
        if job is not None:
            return job
        return self._q_scan_claim(
            self._q_key("running"),
            stale,
            worker_id,
            now,
            expect_status="running",
            stale_before=stale,
            deployment_id=deployment_id,
        )

    def _q_scan_claim(
        self,
        zset_key: str,
        max_score: int,
        worker_id: str,
        now: int,
        expect_status: str,
        stale_before: Optional[int] = None,
        deployment_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Page through ready jobs oldest-first, cheaply pre-filter each page
        by deployment affinity (MGET, advisory only), and CAS-claim the first
        match. Ends when a page comes back empty - worst case one MGET per
        page of foreign jobs, the same order of work as Postgres's index
        scan over the same rows.

        Offset pagination under concurrent claimers can skip entries whose
        rank shifted mid-scan (a peer claimed something on an earlier page).
        That only ends THIS burst early - every poll tick rescans from rank
        0, so a skipped job is picked up next tick; no starvation."""
        from agno.job_queue.session import session_blocked

        page_size = 64
        offset = 0
        session_views: Dict[str, List[Dict[str, Any]]] = {}
        while True:
            raw_ids = self.redis_client.zrangebyscore(zset_key, "-inf", max_score, start=offset, num=page_size)
            if not raw_ids:
                return None
            job_ids = [_q_to_str(raw_id) for raw_id in raw_ids]
            raw_jobs = self.redis_client.mget([self._q_job_key(job_id) for job_id in job_ids])
            for job_id, raw in zip(job_ids, raw_jobs):
                if raw is None:
                    continue
                try:
                    candidate = json.loads(raw if isinstance(raw, str) else raw.decode())
                except (ValueError, AttributeError):
                    continue
                if candidate.get("deployment_id") is not None and candidate.get("deployment_id") != deployment_id:
                    continue
                if (candidate.get("payload") or {}).get("serialize_session") is True:
                    # Advisory pre-check from one view of the session per scan: a backlog
                    # waiting behind a running or paused head would otherwise load the
                    # whole session once per waiting ticket, every poll. The CAS in
                    # _q_try_claim re-reads the session under WATCH and stays the authority.
                    session_key = self._q_session_key(candidate)
                    if session_key not in session_views:
                        session_views[session_key] = self._q_session_members(session_key)
                    if session_blocked(candidate, session_views[session_key]):
                        continue
                job = self._q_try_claim(
                    job_id,
                    worker_id,
                    now,
                    expect_status=expect_status,
                    stale_before=stale_before,
                    deployment_id=deployment_id,
                )
                if job is not None:
                    return job
            offset += page_size

    def _q_try_claim(
        self,
        job_id: str,
        worker_id: str,
        now: int,
        expect_status: str,
        stale_before: Optional[int] = None,
        deployment_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        from redis.exceptions import WatchError

        job_key = self._q_job_key(job_id)
        try:
            with self.redis_client.pipeline() as pipe:
                pipe.watch(job_key)
                raw = pipe.get(job_key)
                if raw is None:
                    pipe.unwatch()
                    return None
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                claimable = (
                    job["status"] == expect_status
                    and job["available_at"] <= now
                    and (job.get("deployment_id") is None or job.get("deployment_id") == deployment_id)
                    and (
                        expect_status == "queued"
                        or (
                            job.get("locked_at") is not None
                            and stale_before is not None
                            and job["locked_at"] <= stale_before
                            and job["attempt"] < job["max_attempts"]
                        )
                    )
                )
                if not claimable:
                    pipe.unwatch()
                    return None
                if (job.get("payload") or {}).get("serialize_session") is True:
                    from agno.job_queue.session import session_blocked

                    # Membership changes commit with each job transition. Watching the
                    # session index fences a concurrent submit, completion or continuation.
                    session_key = self._q_session_key(job)
                    pipe.watch(session_key)
                    member_ids = [_q_to_str(value) for value in pipe.zrange(session_key, 0, -1)]
                    keys = [self._q_job_key(value) for value in member_ids]
                    if keys:
                        pipe.watch(*keys)
                        members = [json.loads(value) for value in pipe.mget(keys) if value is not None]
                        if session_blocked(job, members):
                            pipe.unwatch()
                            return None
                job.update(
                    status="running", locked_by=worker_id, locked_at=now, attempt=job["attempt"] + 1, updated_at=now
                )
                pipe.multi()
                self._q_save_job_in_pipe(pipe, job)
                pipe.zrem(self._q_key("queued"), job_id)
                pipe.zadd(self._q_key("running"), {job_id: now})
                pipe.execute()
                return job
        except WatchError:
            return None

    def _q_fenced_update(
        self, job_id: str, worker_id: str, attempt: int, mutate: Any
    ) -> Tuple["QueueWriteOutcome", Optional[Dict[str, Any]]]:
        """CAS update allowed only for the claim holder of this attempt.

        WatchError means the record changed under us - a CONCURRENT WRITER,
        not a verdict. The single-shot version returned "no" for it, which is
        indistinguishable from a fence rejection: a final heartbeat racing the
        completion could make the completion look fenced, leaving the ticket
        RUNNING with the worker convinced it had settled. Retry the read-CAS
        a bounded number of times and report what actually happened.
        """
        from redis.exceptions import WatchError

        from agno.db.schemas.jobs import QueueWriteOutcome

        job_key = self._q_job_key(job_id)
        for _ in range(10):
            try:
                with self.redis_client.pipeline() as pipe:
                    pipe.watch(job_key)
                    raw = pipe.get(job_key)
                    if raw is None:
                        pipe.unwatch()
                        return QueueWriteOutcome.MISSING, None
                    job = json.loads(raw if isinstance(raw, str) else raw.decode())
                    if job.get("locked_by") != worker_id or job["attempt"] != attempt or job["status"] != "running":
                        pipe.unwatch()
                        return QueueWriteOutcome.FENCED, job
                    mutate(job)
                    pipe.multi()
                    self._q_save_job_in_pipe(pipe, job)
                    # Zset membership is decided ENTIRELY inside this MULTI from
                    # the post-mutate status. A running job keeps (or refreshes)
                    # its running-zset entry in the same transaction - the old
                    # post-EXEC zadd left a crash window where a heartbeaten job
                    # was status="running" but in NO zset: invisible to reclaim
                    # and sweep alike, a permanent zombie.
                    if job["status"] == "running":
                        pipe.zadd(self._q_key("running"), {job_id: job.get("locked_at") or self._q_server_now()})
                    else:
                        pipe.zrem(self._q_key("running"), job_id)
                    if job["status"] == "queued":
                        pipe.zadd(self._q_key("queued"), {job_id: job["available_at"]})
                    pipe.execute()
                    return QueueWriteOutcome.APPLIED, job
            except WatchError:
                continue  # the record changed under us; re-read and re-evaluate
        log_warning(f"Job queue: fenced update for job {job_id} did not settle after 10 attempts (contention)")
        return QueueWriteOutcome.CONTENDED, None

    def heartbeat_jobs(self, worker_id: str, job_ids: List[str]) -> int:
        from agno.db.schemas.jobs import QueueWriteOutcome

        count = 0
        now = self._q_server_now()
        for job_id in job_ids:
            job = self._q_load_job(job_id)
            if job is None:
                continue

            def _beat(j: Dict[str, Any]) -> None:
                j["locked_at"] = now

            outcome, _ = self._q_fenced_update(job_id, worker_id, job["attempt"], _beat)
            if outcome == QueueWriteOutcome.APPLIED:
                count += 1
        return count

    def complete_job(self, job_id: str, worker_id: str, attempt: int, status: str, error: Optional[str] = None) -> bool:
        from agno.db.schemas.jobs import QueueWriteOutcome

        now = self._q_server_now()

        def _complete(job: Dict[str, Any]) -> None:
            job.update(status=status, error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)

        outcome, _ = self._q_fenced_update(job_id, worker_id, attempt, _complete)
        return outcome == QueueWriteOutcome.APPLIED

    def retry_or_fail_job(
        self, job_id: str, worker_id: str, attempt: int, error: str, retry_delay_seconds: int = 30
    ) -> Optional[str]:
        from agno.db.schemas.jobs import QueueWriteOutcome

        now = self._q_server_now()
        outcome_status: Dict[str, str] = {}

        def _retry(job: Dict[str, Any]) -> None:
            if job["attempt"] < job["max_attempts"]:
                job.update(
                    status="queued",
                    error=error,
                    locked_by=None,
                    locked_at=None,
                    available_at=now + retry_delay_seconds,
                    updated_at=now,
                )
                outcome_status["status"] = "queued"
            else:
                job.update(
                    status="failed", error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now
                )
                outcome_status["status"] = "failed"

        outcome, _ = self._q_fenced_update(job_id, worker_id, attempt, _retry)
        return outcome_status.get("status") if outcome == QueueWriteOutcome.APPLIED else None

    def settle_paused_job(self, job_id: str, status: str, error: Optional[str] = None) -> bool:
        """Terminalize a PAUSED ticket whose continue ran INLINE, outside the
        queue (see InMemoryQueueStore.settle_paused_job). WATCH/MULTI CAS on
        status='paused'; a queued/claimed continuation owns the ticket and is
        never clobbered. (Paused jobs are in no queued/running zset.)"""
        from redis.exceptions import WatchError

        if status not in ("completed", "cancelled", "failed"):
            return False
        job_key = self._q_job_key(job_id)
        now = self._q_server_now()
        try:
            with self.redis_client.pipeline() as pipe:
                pipe.watch(job_key)
                raw = pipe.get(job_key)
                if raw is None:
                    pipe.unwatch()
                    return False
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                if job["status"] != "paused":
                    pipe.unwatch()
                    return False
                job.update(status=status, error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)
                pipe.multi()
                self._q_save_job_in_pipe(pipe, job)
                pipe.execute()
                return True
        except WatchError:
            return False

    def cancel_job(self, job_id: str) -> bool:
        # Paused tickets count as waiting: nothing is executing them, and
        # without this a cancelled paused run stayed a paused ticket forever,
        # resurrectable by a later continue. (Paused jobs are in no
        # queued/running zset; the zrem below is a harmless no-op for them.)
        from redis.exceptions import WatchError

        job_key = self._q_job_key(job_id)
        now = self._q_server_now()
        try:
            with self.redis_client.pipeline() as pipe:
                pipe.watch(job_key)
                raw = pipe.get(job_key)
                if raw is None:
                    pipe.unwatch()
                    return False
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                if job["status"] not in ("queued", "paused"):
                    pipe.unwatch()
                    return False
                job.update(status="cancelled", completed_at=now, updated_at=now)
                pipe.multi()
                self._q_save_job_in_pipe(pipe, job)
                pipe.zrem(self._q_key("queued"), job_id)
                pipe.execute()
                return True
        except WatchError:
            return False

    def sweep_exhausted_jobs(self, lock_grace_seconds: int = 60, limit: int = 20) -> List[Dict[str, Any]]:
        stale = self._q_server_now() - lock_grace_seconds
        exhausted: List[Dict[str, Any]] = []
        # PAGE through the whole stale range: a fixed window (the old
        # num=limit*2) made exhausted jobs sitting behind that many
        # stale-but-reclaimable ones invisible on every tick - after a mass
        # crash under a retry budget, terminal failures were starved
        # indefinitely by the reclaim queue ahead of them. The stale range is
        # finite and normally tiny (live jobs' heartbeats advance their zset
        # score out of it), so walking it fully is bounded by the size of the
        # very backlog the sweep exists to clear.
        start = 0
        page = max(limit * 2, 50)
        while len(exhausted) < limit:
            raw_ids = self.redis_client.zrangebyscore(self._q_key("running"), "-inf", stale, start=start, num=page)
            if not raw_ids:
                break
            for raw_id in raw_ids:
                job = self._q_load_job(_q_to_str(raw_id))
                if (
                    job is not None
                    and job["status"] == "running"
                    and job.get("locked_at") is not None
                    and job["locked_at"] <= stale
                    and job["attempt"] >= job["max_attempts"]
                ):
                    exhausted.append(job)
                    if len(exhausted) >= limit:
                        break
            start += len(raw_ids)
        return exhausted

    def acquire_sweep(self, job_id: str, worker_id: str, lock_grace_seconds: int = 60) -> bool:
        """Take ownership of a stale, budget-exhausted running job BEFORE any
        run-row write (WATCH/MULTI CAS). A live heartbeat between the sweep's
        scan and this acquisition wins here, with the run row still
        untouched. Refreshing locked_at doubles as the retry backoff for a
        failing terminalization."""
        from redis.exceptions import WatchError

        job_key = self._q_job_key(job_id)
        now = self._q_server_now()
        stale = now - lock_grace_seconds
        try:
            with self.redis_client.pipeline() as pipe:
                pipe.watch(job_key)
                raw = pipe.get(job_key)
                if raw is None:
                    pipe.unwatch()
                    return False
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                if (
                    job["status"] != "running"
                    or job.get("locked_at") is None
                    or job["locked_at"] > stale
                    or job["attempt"] < job["max_attempts"]
                ):
                    pipe.unwatch()
                    return False
                job.update(locked_by=worker_id, locked_at=now, updated_at=now)
                pipe.multi()
                self._q_save_job_in_pipe(pipe, job)
                # Keep running-zset membership in the same transaction with
                # the refreshed score (the sweep scan keys on this score)
                pipe.zadd(self._q_key("running"), {job_id: now})
                pipe.execute()
                return True
        except WatchError:
            return False

    def settle_swept_job(self, job_id: str, worker_id: str, status: str, error: Optional[str] = None) -> bool:
        """Ownership-keyed settle for the sweeper - see the in-memory store's
        docstring: the sweep reconciles the ticket with what the run row
        says (completed/cancelled/paused/failed), never blind-fails it."""
        from redis.exceptions import WatchError

        if status not in ("completed", "cancelled", "paused", "failed"):
            return False
        job_key = self._q_job_key(job_id)
        now = self._q_server_now()
        try:
            with self.redis_client.pipeline() as pipe:
                pipe.watch(job_key)
                raw = pipe.get(job_key)
                if raw is None:
                    pipe.unwatch()
                    return False
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                if job["status"] != "running" or job.get("locked_by") != worker_id:
                    pipe.unwatch()
                    return False
                job.update(status=status, error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)
                pipe.multi()
                self._q_save_job_in_pipe(pipe, job)
                pipe.zrem(self._q_key("running"), job_id)
                pipe.execute()
                return True
        except WatchError:
            return False

    def get_job(self, job_id: str, strict: bool = False) -> Optional[Dict[str, Any]]:
        """Look up a ticket. strict=True demands failure-propagating
        semantics for fail-closed consumers (see the in-memory store's
        docstring); this load propagates Redis errors in both modes."""
        return self._q_load_job(job_id)

    def session_blocker(self, job_id: str) -> Optional[str]:
        """The id of the ticket a queued serialized job waits behind, or None."""
        from agno.job_queue.session import is_serialized, session_blocker

        job = self._q_load_job(job_id)
        if job is None or job["status"] != "queued" or not is_serialized(job):
            return None
        return session_blocker(job, self._q_session_members(self._q_session_key(job)))

    def count_queued_jobs(self) -> int:
        return int(self.redis_client.zcard(self._q_key("queued")))

    def list_jobs(
        self,
        status: Optional[Union[str, List[str]]] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: Optional[str] = "created_at",
        sort_order: Optional[str] = "desc",
        *,
        session_id: Optional[Union[str, List[str]]] = None,
        user_id: Optional[str] = None,
        raise_on_error: bool = False,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Paginated job listing: (page of jobs, total matching count).

        raise_on_error=True requires read errors to propagate. This store
        already propagates errors in both modes.

        status and session_id accept one value or a list (match any). Loads the full index
        and filters/sorts in Python, like the other Redis list APIs -
        total_count and arbitrary sort fields need the whole set anyway, and
        the index stays small by construction (bounded by max_queue_depth
        plus the retention sweep)."""
        statuses = [status] if isinstance(status, str) else status
        session_ids = [session_id] if isinstance(session_id, str) else session_id
        jobs: List[Dict[str, Any]] = []
        raw_ids = self.redis_client.zrevrange(self._q_key("all"), 0, -1)
        for raw_id in raw_ids:
            job = self._q_load_job(_q_to_str(raw_id))
            if (
                job is not None
                and (statuses is None or job["status"] in statuses)
                and (session_ids is None or job.get("session_id") in session_ids)
                and (user_id is None or job.get("user_id") == user_id)
            ):
                jobs.append(job)
        total_count = len(jobs)
        jobs = apply_sorting(records=jobs, sort_by=sort_by, sort_order=sort_order)
        start = max(page - 1, 0) * limit
        return jobs[start : start + limit], total_count

    def requeue_job(self, job_id: str) -> bool:
        """Operator requeue for a terminally failed/cancelled job: grants
        exactly one more execution by raising max_attempts to attempt + 1."""
        from redis.exceptions import WatchError

        job_key = self._q_job_key(job_id)
        # A same-session submit can win the session index; re-evaluate instead of refusing.
        for _ in range(100):
            now = self._q_server_now()
            try:
                with self.redis_client.pipeline() as pipe:
                    pipe.watch(job_key)
                    raw = pipe.get(job_key)
                    if raw is None:
                        pipe.unwatch()
                        return False
                    job = json.loads(raw if isinstance(raw, str) else raw.decode())
                    if job["status"] not in ("failed", "cancelled"):
                        pipe.unwatch()
                        return False
                    if (job.get("payload") or {}).get("serialize_session") is True:
                        job = self._q_stamp_session_seq(pipe, job)
                    job.update(
                        status="queued",
                        max_attempts=job["attempt"] + 1,
                        available_at=now,
                        locked_by=None,
                        locked_at=None,
                        completed_at=None,
                        updated_at=now,
                    )
                    pipe.multi()
                    self._q_save_job_in_pipe(pipe, job)
                    pipe.zadd(self._q_key("queued"), {job_id: now})
                    pipe.execute()
                    return True
            except WatchError:
                continue
        return False

    def continue_job(self, job_id: str, continue_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Continuation CAS: flip the EXISTING paused ticket back to queued,
        mirroring requeue_job's WATCH/MULTI transition. No new rows, ever -
        id == run_id is load-bearing. Submit-time payload fields are kept;
        payload["continue"] is REPLACED WHOLESALE with this continue's inputs
        (never accumulated across pause cycles). Budget grant: max_attempts =
        attempt + 1 - exactly one more execution, regardless of the configured
        retry budget.

        Returns {"outcome": "queued" | "attach" | "conflict", "job": row}:
        queued = CAS won; attach = ticket already queued/running (double-click
        idempotency - the caller attaches, this click's inputs are discarded);
        conflict = terminal ticket or no ticket (job is the row or None).

        A WatchError means the ticket changed under us (e.g. the raced
        double-click's CAS won): re-evaluate rather than failing, so the
        second click resolves to attach. Exceptions propagate (like
        enqueue_job): this CAS is the durable acceptance of the continue.
        """
        from redis.exceptions import WatchError

        job_key = self._q_job_key(job_id)
        # Same-session submits also contend on the session index; every round commits one of them.
        for _ in range(100):
            now = self._q_server_now()
            try:
                with self.redis_client.pipeline() as pipe:
                    pipe.watch(job_key)
                    raw = pipe.get(job_key)
                    if raw is None:
                        pipe.unwatch()
                        return {"outcome": "conflict", "job": None}
                    job = json.loads(raw if isinstance(raw, str) else raw.decode())
                    if job["status"] in ("completed", "failed", "cancelled"):
                        pipe.unwatch()
                        return {"outcome": "conflict", "job": job}
                    if job["status"] in ("queued", "running"):
                        pipe.unwatch()
                        return {"outcome": "attach", "job": job}
                    payload = dict(job.get("payload") or {})
                    payload["continue"] = dict(continue_payload)
                    job.update(
                        status="queued",
                        payload=payload,
                        max_attempts=job["attempt"] + 1,
                        available_at=now,
                        locked_by=None,
                        locked_at=None,
                        completed_at=None,
                        updated_at=now,
                    )
                    pipe.multi()
                    self._q_save_job_in_pipe(pipe, job)
                    pipe.zadd(self._q_key("queued"), {job_id: now})
                    pipe.execute()
                    return {"outcome": "queued", "job": job}
            except WatchError:
                continue  # ticket changed under us; re-evaluate its new status
        raise RuntimeError("continue_job: ticket contention did not settle after 100 attempts")

    def queue_stats(self) -> Dict[str, Any]:
        now = int(time.time())
        counts: Dict[str, int] = {}
        oldest_queued: Optional[int] = None
        for raw_id in self.redis_client.zrange(self._q_key("all"), 0, -1):
            job = self._q_load_job(_q_to_str(raw_id))
            if job is None:
                continue
            counts[job["status"]] = counts.get(job["status"], 0) + 1
            if job["status"] == "queued":
                age = now - job["created_at"]
                oldest_queued = age if oldest_queued is None else max(oldest_queued, age)
        return {"counts": counts, "oldest_queued_age_seconds": oldest_queued}

    def cleanup_jobs(self, older_than_seconds: int = 86400) -> int:
        """Retention sweep. The delete is CAS-guarded: an operator requeue can
        flip failed->queued between our read and the delete, and an
        unconditional delete would silently vanish the requeued (accepted!)
        run. WATCH + re-check inside the transaction = Postgres's atomic
        DELETE ... WHERE status IN (terminal). Paused tickets are deliberately
        EXEMPT: they must outlive arbitrary human latency to stay continuable;
        cancelling the run is the remedy for abandoned ones."""
        from redis.exceptions import WatchError

        cutoff = int(time.time()) - older_than_seconds
        removed = 0
        for raw_id in self.redis_client.zrange(self._q_key("all"), 0, -1):
            job_id = _q_to_str(raw_id)
            job_key = self._q_job_key(job_id)
            try:
                with self.redis_client.pipeline() as pipe:
                    pipe.watch(job_key)
                    raw = pipe.get(job_key)
                    if raw is None:
                        pipe.unwatch()
                        continue
                    job = json.loads(raw if isinstance(raw, str) else raw.decode())
                    if not (
                        job["status"] in ("completed", "failed", "cancelled")
                        and job.get("completed_at") is not None
                        and job["completed_at"] <= cutoff
                    ):
                        pipe.unwatch()
                        continue
                    pipe.multi()
                    pipe.delete(job_key)
                    # Dedup key dies with the job record (Postgres parity: the
                    # partial-unique index lives exactly as long as the row)
                    if job.get("idempotency_key"):
                        pipe.delete(self._q_idem_key(job.get("user_id"), job["idempotency_key"]))
                    pipe.zrem(self._q_key("all"), job_id)
                    pipe.zrem(self._q_key("queued"), job_id)
                    pipe.zrem(self._q_key("running"), job_id)
                    pipe.execute()
                    removed += 1
            except WatchError:
                continue  # job changed under us (e.g. requeued): leave it alone
        return removed


def _q_to_str(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
