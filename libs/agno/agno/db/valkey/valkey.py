import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Set, Tuple, Union
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import (
    build_os_metrics_state,
    build_single_run_row,
    calculate_date_os_metrics,
    deserialize_run,
    deserialize_session,
    deserialize_sessions,
    drop_legacy_metrics,
    filter_context_runs,
    merge_os_metrics_totals,
    merge_runs_table_with_legacy_blob,
    metric_record_day,
    metrics_starting_date_from_days,
    metrics_starting_date_from_records,
    os_metrics_nested_run_ids,
    os_metrics_rows_to_write,
    os_metrics_state_of,
    resolve_os_metrics_fields,
    total_os_metrics_records,
)
from agno.db.valkey.utils import (
    OS_METRICS_BATCH_SIZE,
    OS_METRICS_LOCK_SECONDS,
    apply_filters,
    apply_pagination,
    apply_sorting,
    build_os_metrics_run,
    build_os_metrics_session,
    calculate_date_metrics,
    create_index_entries,
    deserialize_data,
    deserialize_os_metrics_record,
    fetch_all_sessions_data,
    generate_index_key,
    generate_valkey_key,
    get_all_keys_for_table,
    get_dates_to_calculate_metrics_for,
    get_os_metrics_index_fields,
    os_metrics_record_day,
    os_metrics_record_id,
    record_matches_filter_expr,
    remove_index_entries,
    serialize_data,
    validate_filter_expr,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    from glide_sync import (
        Batch,
        ClusterBatch,
        ConditionalChange,
        ExpirySet,
        ExpiryType,
        GlideClient,
        GlideClientConfiguration,
        GlideClusterClient,
        NodeAddress,
        RangeByIndex,
        RequestError,
        ServerCredentials,
    )
except ImportError:
    raise ImportError("`valkey-glide-sync` not installed. Please install it using `pip install valkey-glide-sync`")


class ValkeyDb(BaseDb):
    def __init__(
        self,
        id: Optional[str] = None,
        valkey_client: Optional[Union[GlideClient, GlideClusterClient]] = None,
        host: str = "localhost",
        port: int = 6379,
        database_id: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = False,
        request_timeout: Optional[int] = None,
        db_prefix: str = "agno",
        client_name: str = "agno_db_client",
        expire: Optional[int] = None,
        session_table: Optional[str] = None,
        runs_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        os_metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        learnings_table: Optional[str] = None,
    ):
        """
        Interface for interacting with a Valkey database using valkey-glide.

        The following order is used to determine the database connection:
            1. Use the valkey_client if provided
            2. Create a new GlideClient from host/port and optional auth/TLS settings
            3. Raise an error if client creation fails

        Args:
            id (Optional[str]): The ID of the database.
            valkey_client (Optional[Union[GlideClient, GlideClusterClient]]): Valkey GLIDE client instance to use.
                If not provided a new client will be created.
            host (str): Valkey server host. Defaults to "localhost".
            port (int): Valkey server port. Defaults to 6379.
            database_id (Optional[int]): Index of the logical database to connect to (e.g. 0-15).
                If not set, the server default (database 0) is used.
            username (Optional[str]): Username for Valkey server authentication.
                If not supplied, the server's "default" user is used.
            password (Optional[str]): Password for Valkey server authentication.
                Required when username is set.
            use_tls (bool): Whether to use TLS for the connection. Defaults to False.
            request_timeout (Optional[int]): Duration in milliseconds to wait for a request to complete.
                If not set, the client default (250 milliseconds) is used.
            db_prefix (str): Prefix for all Valkey keys
            client_name (str): Connection name set via CLIENT SETNAME, visible in CLIENT LIST.
            expire (Optional[int]): TTL for Valkey keys in seconds
            session_table (Optional[str]): Name of the table to store sessions
            runs_table (Optional[str]): Name of the table to store runs (one key per run)
            memory_table (Optional[str]): Name of the table to store memories
            metrics_table (Optional[str]): Name of the table to store metrics
            os_metrics_table (Optional[str]): Name of the table to store OS metrics
            eval_table (Optional[str]): Name of the table to store evaluation runs
            knowledge_table (Optional[str]): Name of the table to store knowledge documents
            traces_table (Optional[str]): Name of the table to store traces
            spans_table (Optional[str]): Name of the table to store spans
            learnings_table (Optional[str]): Name of the table to store learnings

        Raises:
            ValueError: If username is provided without a password.
        """
        if id is None:
            base_seed = f"{host}:{port}" if valkey_client is None else str(valkey_client)
            seed = f"{base_seed}#{db_prefix}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            runs_table=runs_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            os_metrics_table=os_metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
            learnings_table=learnings_table,
        )

        self.db_prefix = db_prefix
        self.expire = expire

        # Zero means never refreshed; get_os_metrics uses this to refresh lazily, at most once per minute
        self._os_metrics_refreshed_at: float = 0.0

        if valkey_client is not None:
            self.valkey_client = valkey_client
        else:
            if username and not password:
                raise ValueError("password must be provided when username is set")
            credentials = ServerCredentials(password=password, username=username) if password else None
            config = GlideClientConfiguration(
                addresses=[NodeAddress(host=host, port=port)],
                database_id=database_id,
                credentials=credentials,
                use_tls=use_tls,
                request_timeout=request_timeout,
                client_name=client_name,
            )
            self.valkey_client = GlideClient.create(config)

    # -- DB methods --

    def _create_pipeline(self) -> Union[Batch, ClusterBatch]:
        """Create a non-atomic batch (pipeline) appropriate for the client type."""
        if isinstance(self.valkey_client, GlideClusterClient):
            return ClusterBatch(is_atomic=False)
        return Batch(is_atomic=False)

    def _exec_pipeline(self, pipeline: Union[Batch, ClusterBatch]) -> Optional[List[Any]]:
        """Execute a batch pipeline on the appropriate client."""
        if isinstance(self.valkey_client, GlideClusterClient) and isinstance(pipeline, ClusterBatch):
            return self.valkey_client.exec(pipeline, raise_on_error=False)
        elif isinstance(self.valkey_client, GlideClient) and isinstance(pipeline, Batch):
            return self.valkey_client.exec(pipeline, raise_on_error=False)
        return None

    def table_exists(self, table_name: str) -> bool:
        """Required by BaseDb. Valkey has no tables and keys are created on
        first write, so existence checks always pass."""
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

        elif table_type == "os_metrics":
            return self.os_metrics_table_name

        elif table_type == "evals":
            return self.eval_table_name

        elif table_type == "knowledge":
            return self.knowledge_table_name

        elif table_type == "traces":
            return self.trace_table_name

        elif table_type == "spans":
            return self.span_table_name

        elif table_type == "learnings":
            return self.learnings_table_name

        raise ValueError(f"Unknown table type: {table_type}")

    def _store_record(
        self, table_type: str, record_id: str, data: Dict[str, Any], index_fields: Optional[List[str]] = None
    ) -> bool:
        """Generic method to store a record in Valkey, considering optional indexing.

        Args:
            table_type (str): The type of table to store the record in.
            record_id (str): The ID of the record to store.
            data (Dict[str, Any]): The data to store in the record.
            index_fields (Optional[List[str]]): The fields to index the record by.

        Returns:
            bool: True if the record was stored successfully, False otherwise.
        """
        try:
            key = generate_valkey_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)
            serialized_data = serialize_data(data)

            expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
            self.valkey_client.set(key, serialized_data, expiry=expiry)

            if index_fields:
                create_index_entries(
                    valkey_client=self.valkey_client,
                    prefix=self.db_prefix,
                    table_type=table_type,
                    record_id=record_id,
                    record_data=data,
                    index_fields=index_fields,
                )

            return True

        except Exception as e:
            log_error(f"Error storing Valkey record: {str(e)}")
            return False

    def _get_record(self, table_type: str, record_id: str) -> Optional[Dict[str, Any]]:
        """Generic method to get a record from Valkey.

        Args:
            table_type (str): The type of table to get the record from.
            record_id (str): The ID of the record to get.

        Returns:
            Optional[Dict[str, Any]]: The record data if found, None otherwise.
        """
        try:
            key = generate_valkey_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)

            data = self.valkey_client.get(key)
            if data is None:
                return None

            # glide returns bytes, decode if needed
            data_str: str = data.decode("utf-8") if isinstance(data, bytes) else data

            return deserialize_data(data_str)  # type: ignore

        except Exception as e:
            log_error(f"Error getting record {record_id}: {str(e)}")
            return None

    def _delete_record(self, table_type: str, record_id: str, index_fields: Optional[List[str]] = None) -> bool:
        """Generic method to delete a record from Valkey.

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
                        valkey_client=self.valkey_client,
                        prefix=self.db_prefix,
                        table_type=table_type,
                        record_id=record_id,
                        record_data=record_data,
                        index_fields=index_fields,
                    )

            key = generate_valkey_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)
            result = self.valkey_client.delete([key])
            if result is None or result == 0:
                return False

            return True

        except Exception as e:
            log_error(f"Error deleting record {record_id}: {str(e)}")
            return False

    def _get_all_records(self, table_type: str) -> List[Dict[str, Any]]:
        """Generic method to get all records for a table type using pipeline batching.

        Args:
            table_type (str): The type of table to get the records from.

        Returns:
            List[Dict[str, Any]]: The records data if found, empty list otherwise.

        Raises:
            Exception: If any error occurs while getting the records.
        """
        try:
            keys = get_all_keys_for_table(
                valkey_client=self.valkey_client, prefix=self.db_prefix, table_type=table_type
            )

            if not keys:
                return []

            # Batch all GETs in a single pipeline round trip
            pipeline = self._create_pipeline()
            for key in keys:
                pipeline.get(key)

            results = self._exec_pipeline(pipeline)
            if not results:
                return []

            records = []
            for raw in results:
                if raw is None or isinstance(raw, RequestError):
                    continue
                data_str: str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else ""
                if data_str:
                    records.append(deserialize_data(data_str))

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
        value = self.valkey_client.get(self._schema_version_key(table_name))
        if value is None:
            return "2.0.0"
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    def upsert_schema_version(self, table_name: str = "", version: str = "") -> None:
        """Record the schema version stamp for the given table.

        No TTL: the stamp must outlive ``self.expire``.
        """
        self.valkey_client.set(self._schema_version_key(table_name), version)

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
        """Upsert a single run as its own Valkey key + maintain the session index (O(1)).

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

            index_key = self._runs_by_session_index_key(session_id)
            run_key = generate_valkey_key(prefix=self.db_prefix, table_type="runs", key_id=row["run_id"])

            pipeline = self._create_pipeline()
            expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
            pipeline.set(run_key, serialize_data(row), expiry=expiry)
            pipeline.zadd(index_key, {row["run_id"]: float(row.get("run_index") or 0)})
            if self.expire is not None:
                pipeline.expire(index_key, self.expire)
            self._exec_pipeline(pipeline)

            # Maintain field indexes for cross-session run queries
            create_index_entries(
                valkey_client=self.valkey_client,
                prefix=self.db_prefix,
                table_type="runs",
                record_id=row["run_id"],
                record_data=row,
                index_fields=["session_id", "user_id", "agent_id", "team_id", "workflow_id", "run_type", "status"],
            )
        except Exception as e:
            log_error(f"Exception upserting run into Valkey: {str(e)}")
            raise e

    def _get_session_run_rows(self, session_id: str) -> List[Dict[str, Any]]:
        """Get the run rows for a session, ordered by run_index, in a single batched read."""
        index_key = self._runs_by_session_index_key(session_id)
        try:
            run_ids: List[str] = [
                m.decode("utf-8") if isinstance(m, bytes) else str(m)
                for m in self.valkey_client.zrange(index_key, RangeByIndex(0, -1))
            ]
        except Exception:
            run_ids = []

        if not run_ids:
            return []

        pipeline = self._create_pipeline()
        for run_id in run_ids:
            pipeline.get(generate_valkey_key(prefix=self.db_prefix, table_type="runs", key_id=run_id))
        results = self._exec_pipeline(pipeline)
        if not results:
            return []

        rows: List[Dict[str, Any]] = []
        for raw in results:
            if raw is None or isinstance(raw, RequestError):
                continue
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            if raw_str:
                rows.append(deserialize_data(raw_str))

        # ZRANGE breaks equal run_index scores lexicographically by run_id; sort so
        # the order matches get_runs
        rows.sort(key=lambda r: (r.get("run_index") or 0, r.get("created_at") or 0))
        return rows

    def _get_session_runs_data(self, session_id: str) -> List[Dict[str, Any]]:
        """Get raw run_data dicts for a session, ordered by run_index."""
        return [row["run_data"] for row in self._get_session_run_rows(session_id) if row.get("run_data") is not None]

    def _get_sessions_runs_data(self, session_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Get raw run_data dicts for several sessions, grouped by session_id."""
        return {sid: self._get_session_runs_data(sid) for sid in session_ids}

    def _delete_session_runs(self, session_id: str) -> int:
        """Delete every run row associated with a session (and the session's run index)."""
        index_key = self._runs_by_session_index_key(session_id)
        try:
            run_ids: List[str] = [
                m.decode("utf-8") if isinstance(m, bytes) else str(m)
                for m in self.valkey_client.zrange(index_key, RangeByIndex(0, -1))
            ]
        except Exception:
            run_ids = []

        deleted = 0
        for run_id in run_ids:
            if self._delete_record(
                table_type="runs",
                record_id=run_id,
                index_fields=["session_id", "user_id", "agent_id", "team_id", "workflow_id", "run_type", "status"],
            ):
                deleted += 1
        # Drop the sorted-set itself
        try:
            self.valkey_client.delete([index_key])
        except Exception:
            pass
        return deleted

    def cleanup_legacy_runs_field(self, force: bool = False) -> bool:
        """Unset the legacy ``runs`` field from session records in Valkey.

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
        """Read a single run from Valkey."""
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
                rows: List[Dict[str, Any]] = self._get_session_run_rows(session_id)
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
        """Delete a single run from Valkey (and its entry in the session's run index)."""
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
                    self.valkey_client.zrem(self._runs_by_session_index_key(sid), [run_id])
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
        """Delete a session from Valkey.

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
        """Delete multiple sessions from Valkey using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the sessions.
        """
        if not session_ids:
            return

        try:
            index_fields = ["user_id", "agent_id", "team_id", "workflow_id", "session_type"]

            # Phase 1: Batch-read all sessions (needed for index cleanup and user_id filtering)
            read_pipeline = self._create_pipeline()
            keys: List[str] = []
            for session_id in session_ids:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="sessions", key_id=session_id)
                keys.append(key)
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)

            # Phase 2: Build delete pipeline
            delete_pipeline = self._create_pipeline()
            delete_count = 0
            deleted_session_ids: List[str] = []

            for i, session_id in enumerate(session_ids):
                raw = read_results[i] if read_results else None
                if raw is None or isinstance(raw, RequestError):
                    continue

                raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                if not raw_str:
                    continue

                record_data = deserialize_data(raw_str)

                # Filter by user_id if provided
                if user_id is not None and record_data.get("user_id") != user_id:
                    continue

                # Remove index entries
                for field in index_fields:
                    if field in record_data and record_data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "sessions", field, str(record_data[field]))
                        delete_pipeline.srem(index_key, [session_id])

                delete_pipeline.delete([keys[i]])
                delete_count += 1
                deleted_session_ids.append(session_id)

            if delete_count > 0:
                self._exec_pipeline(delete_pipeline)

            # Cascade-delete runs for every session actually removed
            for session_id in deleted_session_ids:
                self._delete_session_runs(session_id)

            log_debug(f"Successfully deleted {delete_count} sessions")

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
        """Read a session from Valkey.

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
                # No query engine to push "last N" down: filter+slice in memory to
                # match the SQL fast path (drop member/skip-status runs, then last N).
                session["runs"] = filter_context_runs(session["runs"] or [])[-runs_limit:]

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Exception reading session: {str(e)}")
            raise e

    # TODO: Use index sets (agno:sessions:index:user_id:<id>) to avoid full scan when filtering by user_id/agent_id
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
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        """Get all sessions matching the given filters.

        Args:
            session_type (Optional[SessionType]): The type of session to filter by.
            user_id (Optional[str]): The ID of the user to filter by.
            component_id (Optional[str]): The ID of the component (agent/team/workflow) to filter by.
            session_name (Optional[str]): The name of the session to filter by (case-insensitive substring).
            start_timestamp (Optional[int]): Unix timestamp lower bound on created_at.
            end_timestamp (Optional[int]): Unix timestamp upper bound on created_at.
            limit (Optional[int]): The maximum number of sessions to return.
            page (Optional[int]): The 1-based page number (used with limit).
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The sort direction ('asc' or 'desc').
            deserialize (Optional[bool]): If True, return typed Session objects; if False,
                return a tuple of (raw dicts, total_count).

        Returns:
            Union[List[Session], Tuple[List[Dict[str, Any]], int]]: Deserialized session
                objects when deserialize=True, or a (records, total_count) tuple otherwise.
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

            # Attach runs from the runs keys, merged with any legacy `runs` blob
            runs_by_session = self._get_sessions_runs_data([s["session_id"] for s in sessions])
            for s in sessions:
                s["runs"] = merge_runs_table_with_legacy_blob(runs_by_session.get(s["session_id"], []), s.get("runs"))

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
        """Rename a session in Valkey.

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
        """Insert or update a session in Valkey.

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

            # Preserve the legacy `runs` field as a frozen backup. _store_record does
            # a full SET (whole-record replace), and session.to_dict(include_runs=False)
            # omits `runs`, so a bare write would silently erase any pre-v3 history
            # that lives only in the legacy blob (upgrade-without-migration data loss).
            # Only cleanup_legacy_runs_field() should drop it, explicitly.
            if existing and existing.get("runs") is not None:
                data["runs"] = existing["runs"]

            success = self._store_record(
                table_type="sessions",
                record_id=session.session_id,
                data=data,
                index_fields=index_fields,
            )
            if not success:
                return None

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
        Bulk upsert multiple sessions using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            sessions (List[Session]): List of sessions to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.
            preserve_updated_at (bool): Whether to preserve the existing updated_at timestamp.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not sessions:
            return []

        try:
            valid_sessions = [s for s in sessions if s is not None]
            if not valid_sessions:
                return []

            now = int(time.time())

            # Phase 1: Batch-read existing sessions to check user_id ownership
            read_pipeline = self._create_pipeline()
            session_keys: List[str] = []
            for session in valid_sessions:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="sessions", key_id=session.session_id)
                session_keys.append(key)
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)

            # Build map of existing sessions
            existing_map: Dict[str, Dict[str, Any]] = {}
            if read_results:
                for i, raw in enumerate(read_results):
                    if raw is not None and not isinstance(raw, RequestError):
                        raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                        if raw_str:
                            existing_map[valid_sessions[i].session_id] = deserialize_data(raw_str)

            # Phase 2: Prepare data and batch-write
            write_pipeline = self._create_pipeline()
            prepared: List[Tuple[Session, Dict[str, Any], int]] = []
            write_cmd_count = 0

            for session in valid_sessions:
                session_dict = session.to_dict(include_runs=False)

                # Check user_id ownership
                existing = existing_map.get(session.session_id)
                if (
                    existing
                    and existing.get("user_id") is not None
                    and existing.get("user_id") != session_dict.get("user_id")
                ):
                    continue

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
                        "created_at": session_dict.get("created_at") or now,
                        "updated_at": session_dict.get("updated_at") if preserve_updated_at else now,
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
                        "created_at": session_dict.get("created_at") or now,
                        "updated_at": session_dict.get("updated_at") if preserve_updated_at else now,
                    }
                    index_fields = ["user_id", "team_id", "session_type"]
                else:
                    data = {
                        "session_id": session_dict.get("session_id"),
                        "session_type": SessionType.WORKFLOW.value,
                        "workflow_id": session_dict.get("workflow_id"),
                        "user_id": session_dict.get("user_id"),
                        "workflow_data": session_dict.get("workflow_data"),
                        "session_data": session_dict.get("session_data"),
                        "metadata": session_dict.get("metadata"),
                        "created_at": session_dict.get("created_at") or now,
                        "updated_at": session_dict.get("updated_at") if preserve_updated_at else now,
                        "agent_id": None,
                        "team_id": None,
                        "agent_data": None,
                        "team_data": None,
                        "summary": None,
                    }
                    index_fields = ["user_id", "workflow_id", "session_type"]

                # Preserve the legacy `runs` field as a frozen backup. The pipeline
                # SET replaces the whole record, and session.to_dict(include_runs=False)
                # omits `runs`, so a bare write would erase any pre-v3 history that
                # lives only in the legacy blob. Only cleanup_legacy_runs_field()
                # should drop it, explicitly.
                if existing and existing.get("runs") is not None:
                    data["runs"] = existing["runs"]

                key = generate_valkey_key(prefix=self.db_prefix, table_type="sessions", key_id=session.session_id)
                expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
                set_cmd_index = write_cmd_count
                write_pipeline.set(key, serialize_data(data), expiry=expiry)
                write_cmd_count += 1

                for field in index_fields:
                    if field in data and data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "sessions", field, str(data[field]))
                        write_pipeline.sadd(index_key, [session.session_id])
                        write_cmd_count += 1

                prepared.append((session, data, set_cmd_index))

            write_results = self._exec_pipeline(write_pipeline) if prepared else None

            # Build return values, skipping records whose SET failed
            results: List[Union[Session, Dict[str, Any]]] = []
            for session, data, set_cmd_index in prepared:
                if write_results is None or isinstance(write_results[set_cmd_index], RequestError):
                    continue

                # Runs are persisted separately via upsert_run by the caller.
                # Attach the in-memory runs for callers.
                data["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]

                if not deserialize:
                    results.append(data)
                    continue
                deserialized_session: Optional[Session] = None
                if isinstance(session, AgentSession):
                    deserialized_session = AgentSession.from_dict(data)
                elif isinstance(session, TeamSession):
                    deserialized_session = TeamSession.from_dict(data)
                else:
                    deserialized_session = WorkflowSession.from_dict(data)
                if deserialized_session is not None:
                    results.append(deserialized_session)
            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert: {str(e)}")
            return []

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        """Delete a user memory from Valkey.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user. If provided, verifies the memory belongs to this user before deleting.

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
        """Delete user memories from Valkey using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user. If provided, only deletes memories belonging to this user.
        """
        if not memory_ids:
            return

        try:
            index_fields = ["user_id", "agent_id", "team_id", "workflow_id"]

            # Phase 1: Batch-read all memories (needed for index cleanup and user_id filtering)
            read_pipeline = self._create_pipeline()
            keys: List[str] = []
            for memory_id in memory_ids:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="memories", key_id=memory_id)
                keys.append(key)
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)

            # Phase 2: Build delete pipeline
            delete_pipeline = self._create_pipeline()
            delete_count = 0

            for i, memory_id in enumerate(memory_ids):
                raw = read_results[i] if read_results else None
                if raw is None or isinstance(raw, RequestError):
                    continue

                raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                if not raw_str:
                    continue

                record_data = deserialize_data(raw_str)

                # Filter by user_id if provided
                if user_id is not None and record_data.get("user_id") != user_id:
                    log_debug(f"Memory {memory_id} does not belong to user {user_id}, skipping deletion")
                    continue

                # Remove index entries
                for field in index_fields:
                    if field in record_data and record_data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "memories", field, str(record_data[field]))
                        delete_pipeline.srem(index_key, [memory_id])

                delete_pipeline.delete([keys[i]])
                delete_count += 1

            if delete_count > 0:
                self._exec_pipeline(delete_pipeline)

        except Exception as e:
            log_error(f"Error deleting user memories: {str(e)}")
            raise e

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from Valkey.

        Args:
            user_id: If provided, only return topics from memories belonging to this user.

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
        """Get a memory from Valkey.

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
        """Get all memories from Valkey as UserMemory objects.

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

            # Apply topic filter ("topics" may be stored as None, so coalesce to an empty list)
            if topics is not None:
                filtered_memories = [
                    m for m in filtered_memories if any(topic in (m.get("topics") or []) for topic in topics)
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
        """Get user memory stats from Valkey.

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
                updated_at = memory.get("updated_at") or 0
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
        """Upsert a user memory in Valkey.

        Args:
            memory (UserMemory): The memory to upsert.

        Returns:
            Optional[UserMemory]: The upserted memory data if successful, None otherwise.
        """
        try:
            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            created_at = memory.created_at
            existing_record = self._get_record("memories", memory.memory_id)
            if existing_record:
                # Update the existing record while preserving created_at
                created_at = existing_record.get("created_at", memory.created_at)

            data = {
                "user_id": memory.user_id,
                "agent_id": memory.agent_id,
                "team_id": memory.team_id,
                "memory_id": memory.memory_id,
                "memory": memory.memory,
                "topics": memory.topics,
                "input": memory.input,
                "feedback": memory.feedback,
                "created_at": created_at,
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
        Bulk upsert multiple user memories using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            memories (List[UserMemory]): List of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.
            preserve_updated_at (bool): Whether to preserve the existing updated_at timestamp.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not memories:
            return []

        try:
            index_fields = ["user_id", "agent_id", "team_id", "workflow_id"]
            now = int(time.time())

            valid_memories = [m for m in memories if m is not None]
            for memory in valid_memories:
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

            # Phase 1: Batch-read existing memories to preserve created_at, as the
            # single-record upsert_user_memory path does.
            read_pipeline = self._create_pipeline()
            for memory in valid_memories:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="memories", key_id=str(memory.memory_id))
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)
            existing_map: Dict[str, Dict[str, Any]] = {}
            if read_results:
                for i, raw in enumerate(read_results):
                    if raw is None or isinstance(raw, RequestError):
                        continue
                    raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                    if raw_str:
                        existing_map[str(valid_memories[i].memory_id)] = deserialize_data(raw_str)

            # Prepare all memory data
            prepared: List[Dict[str, Any]] = []
            for memory in valid_memories:
                existing = existing_map.get(str(memory.memory_id))
                created_at = existing.get("created_at", memory.created_at) if existing else memory.created_at

                data = {
                    "user_id": memory.user_id,
                    "agent_id": memory.agent_id,
                    "team_id": memory.team_id,
                    "memory_id": memory.memory_id,
                    "memory": memory.memory,
                    "topics": memory.topics,
                    "input": memory.input,
                    "feedback": memory.feedback,
                    "created_at": created_at,
                    "updated_at": memory.updated_at if preserve_updated_at else now,
                }
                prepared.append(data)

            if not prepared:
                return []

            # Batch all writes in a single pipeline
            pipeline = self._create_pipeline()
            expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
            set_cmd_indices: List[int] = []
            write_cmd_count = 0
            for data in prepared:
                memory_id = str(data["memory_id"])
                key = generate_valkey_key(prefix=self.db_prefix, table_type="memories", key_id=memory_id)
                set_cmd_indices.append(write_cmd_count)
                pipeline.set(key, serialize_data(data), expiry=expiry)
                write_cmd_count += 1

                # Add index entries
                for field in index_fields:
                    if field in data and data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "memories", field, str(data[field]))
                        pipeline.sadd(index_key, [memory_id])
                        write_cmd_count += 1

            write_results = self._exec_pipeline(pipeline)

            # Build return values, skipping records whose SET failed
            results: List[Union[UserMemory, Dict[str, Any]]] = []
            for data, set_cmd_index in zip(prepared, set_cmd_indices):
                if write_results is None or isinstance(write_results[set_cmd_index], RequestError):
                    continue
                if deserialize:
                    results.append(UserMemory.from_dict(data))
                else:
                    results.append(data)
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
            keys = get_all_keys_for_table(
                valkey_client=self.valkey_client, prefix=self.db_prefix, table_type="memories"
            )

            if keys:
                # Delete all memory keys in a single batch operation
                self.valkey_client.delete(keys)  # type: ignore[arg-type]

        except Exception as e:
            log_error(f"Exception deleting all memories: {str(e)}")
            raise e

    # -- Metrics methods --

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions for metrics calculation.

        Args:
            start_timestamp (Optional[int]): The start timestamp to filter by.
            end_timestamp (Optional[int]): The end timestamp to filter by.

        Returns:
            List[Dict[str, Any]]: The list of sessions.

        Raises:
            Exception: If any error occurs while getting the sessions.
        """
        try:
            all_sessions = self._get_all_records("sessions")

            # Filter by timestamp if provided
            if start_timestamp is not None or end_timestamp is not None:
                filtered_sessions = []
                for session in all_sessions:
                    created_at = session.get("created_at", 0)
                    if start_timestamp is not None and created_at < start_timestamp:
                        continue
                    if end_timestamp is not None and created_at > end_timestamp:
                        continue
                    filtered_sessions.append(session)
                all_sessions = filtered_sessions

            # Attach lightweight run info (model + provider) per session. For Valkey, we
            # walk the per-session sorted-set index and read each run row — cheap for
            # typical session sizes, and `calculate_date_metrics` only needs len(runs)
            # plus run["model"] / run["model_provider"].
            runs_by_session = self._get_sessions_runs_data(
                [s["session_id"] for s in all_sessions if s.get("session_id")]
            )
            for session in all_sessions:
                sid = session.get("session_id")
                if not sid:
                    continue
                lightweight = [
                    {"model": rd.get("model"), "model_provider": rd.get("model_provider")}
                    for rd in runs_by_session.get(sid, [])
                ]
                if lightweight or not session.get("runs"):
                    session["runs"] = lightweight

            return all_sessions

        except Exception as e:
            log_error(f"Error reading sessions for metrics: {str(e)}")
            raise e

    def _get_metrics_calculation_starting_date(self) -> Optional[date]:
        """Get the first date for which metrics calculation is needed.

        Returns:
            Optional[date]: The first date for which metrics calculation is needed.

        Raises:
            Exception: If any error occurs while getting the metrics calculation starting date.
        """
        try:
            all_metrics = self._get_all_records("metrics")

            resume_date = metrics_starting_date_from_records(all_metrics)
            if resume_date is not None:
                return resume_date

            # No metrics records, find first session
            sessions_raw, _ = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
            if sessions_raw:
                first_session_date = sessions_raw[0]["created_at"]  # type: ignore
                return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

            return None

        except Exception as e:
            log_error(f"Error getting metrics starting date: {str(e)}")
            raise e

    def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics.

        Returns:
            Optional[list[dict]]: The list of metrics.

        Raises:
            Exception: If any error occurs while calculating the metrics.
        """
        try:
            starting_date = self._get_metrics_calculation_starting_date()
            if starting_date is None:
                log_info("No session data found. Won't calculate metrics.")
                return None

            dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
            if not dates_to_process:
                log_info("Metrics already calculated for all relevant dates.")
                return None

            start_timestamp = int(
                datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
            )
            end_timestamp = int(
                datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )

            sessions = self._get_all_sessions_for_metrics_calculation(
                start_timestamp=start_timestamp, end_timestamp=end_timestamp
            )
            all_sessions_data = fetch_all_sessions_data(
                sessions=sessions, dates_to_process=dates_to_process, start_timestamp=start_timestamp
            )
            if not all_sessions_data:
                log_info("No new session data found. Won't calculate metrics.")
                return None

            results = []
            for date_to_process in dates_to_process:
                date_key = date_to_process.isoformat()
                sessions_for_date = all_sessions_data.get(date_key, {})

                # Skip dates with no sessions
                if not any(len(sessions) > 0 for sessions in sessions_for_date.values()):
                    continue

                # calculate_date_metrics returns a LIST: one record per
                # distinct user_id (plus the empty-string bucket for unowned
                # sessions). Iterate and upsert each.
                for metrics_record in calculate_date_metrics(date_to_process, sessions_for_date):
                    # Preserve created_at across re-runs.
                    existing_record = self._get_record("metrics", metrics_record["id"])
                    if existing_record:
                        metrics_record["created_at"] = existing_record.get("created_at", metrics_record["created_at"])

                    success = self._store_record("metrics", metrics_record["id"], metrics_record)
                    if success:
                        results.append(metrics_record)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Error calculating metrics: {str(e)}")
            raise e

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range.

        Args:
            starting_date (Optional[date]): The starting date to filter by.
            ending_date (Optional[date]): The ending date to filter by.
            user_id (Optional[str]): When provided, returns only that user's
                per-user bucket. When ``None``, returns ALL buckets including
                the empty-string unowned bucket.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the list of metrics and the latest updated_at.

        Raises:
            Exception: If any error occurs while getting the metrics.
        """
        try:
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

            # Before the owner filter, not inside it: this is the one backend that ever wrote a
            # record holding a whole day under the unowned bucket, so "" would select it
            all_metrics = drop_legacy_metrics(all_metrics)

            # Filter by user_id if requested. A whole-day record with no per-user rows covering
            # its day survives the drop above and also carries "", but it holds the day for
            # every user, so it must never match the unowned bucket. users_count tells them
            # apart: the fresh unowned bucket has no owner to count and stays at zero.
            if user_id is not None:
                all_metrics = [
                    m
                    for m in all_metrics
                    if m.get("user_id") == user_id and not (user_id == "" and m.get("users_count"))
                ]

            # Get latest updated_at
            latest_updated_at = None
            if all_metrics:
                latest_updated_at = max(metric.get("updated_at", 0) for metric in all_metrics)

            # Map the sentinel empty-string user_id back to None.
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

    # -- OS metrics methods --

    def _os_metrics_lock_key(self) -> str:
        """Key held by the one process calculating OS metrics. Kept out of the os_metrics keys, which hold records."""
        return f"{self.db_prefix}:os_metrics_lock"

    def _os_metrics_state_key(self) -> str:
        """Key holding when any OS metrics record was last written or deleted, and the hash of the state."""
        return generate_valkey_key(prefix=self.db_prefix, table_type="os_metrics", key_id="state")

    def _acquire_os_metrics_lock(self, wait_for_rebuild: bool) -> Optional[str]:
        """Take the OS metrics lock, so one process calculates OS metrics at a time.

        Args:
            wait_for_rebuild (bool): Wait for a rebuild another process is running. When False, skip instead.

        Returns:
            Optional[str]: The token the lock is held with, None when another process holds it.
        """
        token = str(uuid4())
        while not self.valkey_client.set(
            self._os_metrics_lock_key(),
            token,
            conditional_set=ConditionalChange.ONLY_IF_DOES_NOT_EXIST,
            expiry=ExpirySet(ExpiryType.SEC, OS_METRICS_LOCK_SECONDS),
        ):
            if not wait_for_rebuild:
                return None
            time.sleep(0.1)
        return token

    def _extend_os_metrics_lock(self, token: str) -> bool:
        """Hold the OS metrics lock for OS_METRICS_LOCK_SECONDS more. False when it is no longer held with the token."""
        holder = self.valkey_client.get(self._os_metrics_lock_key())
        # glide returns bytes, decode if needed
        if (holder.decode("utf-8") if isinstance(holder, bytes) else holder) != token:
            return False
        self.valkey_client.expire(self._os_metrics_lock_key(), OS_METRICS_LOCK_SECONDS)
        return True

    def _release_os_metrics_lock(self, token: str) -> None:
        """Release the OS metrics lock, unless it expired and another process holds it."""
        holder = self.valkey_client.get(self._os_metrics_lock_key())
        if (holder.decode("utf-8") if isinstance(holder, bytes) else holder) == token:
            self.valkey_client.delete([self._os_metrics_lock_key()])

    def _exec_os_metrics_pipeline(self, pipeline: Union[Batch, ClusterBatch]) -> List[Any]:
        """Execute a batch pipeline of an OS metrics rebuild or read.

        Unlike _exec_pipeline, a command that failed raises.
        """
        results = self._exec_pipeline(pipeline) or []
        for result in results:
            if isinstance(result, RequestError):
                raise result
        return results

    def _get_records_for_os_metrics_calculation(
        self, table_type: str, start_timestamp: int, end_timestamp: int, lock_token: str
    ) -> Dict[date, List[Dict[str, Any]]]:
        """Get the sessions or runs created in the given time range, with only what OS metrics count.

        Unlike _get_all_records, a failed read raises, so a rebuild never writes a day without its records.

        Args:
            table_type (str): "sessions" or "runs".
            start_timestamp (int): The start of the range, included.
            end_timestamp (int): The end of the range, not included.
            lock_token (str): The token the OS metrics lock is held with.

        Returns:
            Dict[date, List[Dict[str, Any]]]: The records, trimmed to what OS metrics count, by the UTC day they
                were created on.
        """
        keys = get_all_keys_for_table(valkey_client=self.valkey_client, prefix=self.db_prefix, table_type=table_type)

        records_by_day: Dict[date, List[Dict[str, Any]]] = {}
        for batch_start in range(0, len(keys), OS_METRICS_BATCH_SIZE):
            # Extend the lock with every batch, so a long read keeps it
            self._extend_os_metrics_lock(lock_token)
            pipeline = self._create_pipeline()
            for key in keys[batch_start : batch_start + OS_METRICS_BATCH_SIZE]:
                pipeline.get(key)
            for raw in self._exec_os_metrics_pipeline(pipeline):
                if not raw:
                    continue
                record = deserialize_data(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                created_at = record.get("created_at")
                if created_at is None or not start_timestamp <= created_at < end_timestamp:
                    continue
                day = datetime.fromtimestamp(created_at, tz=timezone.utc).date()
                records_by_day.setdefault(day, []).append(
                    build_os_metrics_run(record) if table_type == "runs" else build_os_metrics_session(record)
                )

        return records_by_day

    def _get_os_metrics_record_ids(self, index_field: str, index_values: List[str]) -> List[List[str]]:
        """Get the IDs of the OS metrics records indexed under each of the given values of a field.

        Every command reads a single key, so it works on a cluster too.

        Args:
            index_field (str): The indexed field: "date", "user_id" or "aggregation_period".
            index_values (List[str]): The values of the field to get the record IDs of.

        Returns:
            List[List[str]]: The record IDs of each value, in the order of the values.
        """
        if not index_values:
            return []
        pipeline = self._create_pipeline()
        for index_value in index_values:
            pipeline.smembers(generate_index_key(self.db_prefix, "os_metrics", index_field, index_value))
        # glide returns bytes, decode if needed
        return [
            [record_id.decode("utf-8") if isinstance(record_id, bytes) else record_id for record_id in record_ids or []]
            for record_ids in self._exec_os_metrics_pipeline(pipeline)
        ]

    def _get_os_metrics_records(self, record_ids: List[str]) -> List[Dict[str, Any]]:
        """Get the OS metrics records with the given IDs, a batch at a time.

        Args:
            record_ids (List[str]): The IDs of the records to get.

        Returns:
            List[Dict[str, Any]]: The records that exist, their date read back as a date.
        """
        records = []
        for batch_start in range(0, len(record_ids), OS_METRICS_BATCH_SIZE):
            pipeline = self._create_pipeline()
            for record_id in record_ids[batch_start : batch_start + OS_METRICS_BATCH_SIZE]:
                pipeline.get(generate_valkey_key(prefix=self.db_prefix, table_type="os_metrics", key_id=record_id))
            for raw in self._exec_os_metrics_pipeline(pipeline):
                # A record that expired is left out, as if the day did not have it
                if not raw:
                    continue
                records.append(
                    deserialize_os_metrics_record(
                        deserialize_data(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                    )
                )
        return records

    def _get_stored_os_metrics_state(self) -> Dict[str, Any]:
        """Get the state of the OS metrics, as build_os_metrics_state builds it, from the state key."""
        data = self.valkey_client.get(self._os_metrics_state_key())
        if not data:
            return {}
        return deserialize_data(data.decode("utf-8") if isinstance(data, bytes) else data)

    def _store_os_metrics_records(
        self,
        changed_rows: List[Dict[str, Any]],
        stale_rows: List[Dict[str, Any]],
        previous_state: Dict[str, Any],
        state: Dict[str, Any],
    ) -> None:
        """Save the changed OS metrics records of a day, and delete the ones the day no longer has.

        The state key is written with the last batch, so it moves only once the whole day is saved.

        Args:
            changed_rows (List[Dict[str, Any]]): The records to write.
            stale_rows (List[Dict[str, Any]]): The stored records to delete.
            previous_state (Dict[str, Any]): The state before the day is saved.
            state (Dict[str, Any]): The state once the day is saved, for the state key.
        """
        # The state is marked before any record is written, so a day saved without its state is not taken as unchanged
        self.valkey_client.set(self._os_metrics_state_key(), serialize_data({**previous_state, "rebuilding": True}))
        expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
        # The total record of a day is written last, so a day whose write failed part way has none
        changed_rows = sorted(changed_rows, key=lambda row: row["aggregation_period"] != "daily")
        pipeline = self._create_pipeline()
        for position, row in enumerate([*stale_rows, *changed_rows]):
            key = generate_valkey_key(prefix=self.db_prefix, table_type="os_metrics", key_id=row["id"])
            if position < len(stale_rows):
                for field in get_os_metrics_index_fields(row):
                    index_key = generate_index_key(self.db_prefix, "os_metrics", field, str(row[field]))
                    pipeline.srem(index_key, [row["id"]])
                pipeline.delete([key])
            else:
                pipeline.set(key, serialize_data(row), expiry=expiry)
                for field in get_os_metrics_index_fields(row):
                    index_key = generate_index_key(self.db_prefix, "os_metrics", field, str(row[field]))
                    pipeline.sadd(index_key, [row["id"]])
            if (position + 1) % OS_METRICS_BATCH_SIZE == 0:
                self._exec_os_metrics_pipeline(pipeline)
                pipeline = self._create_pipeline()
        # No TTL: the state must outlive ``self.expire``
        pipeline.set(self._os_metrics_state_key(), serialize_data(state))
        self._exec_os_metrics_pipeline(pipeline)

    def calculate_os_metrics(self) -> Optional[List[Dict[str, Any]]]:
        """Calculate OS metrics for all dates without complete OS metrics.

        Returns:
            Optional[List[Dict[str, Any]]]: The calculated OS metrics.

        Raises:
            Exception: If any error occurs while calculating the OS metrics.
        """
        try:
            return self._calculate_os_metrics(wait_for_rebuild=True)

        except Exception as e:
            log_error(f"Error calculating OS metrics: {str(e)}")
            raise e

    def refresh_os_metrics(self) -> Tuple[Optional[int], Optional[int], bool]:
        """Calculate OS metrics for all dates without complete OS metrics, and report whether any record changed.

        Returns:
            Tuple[Optional[int], Optional[int], bool]: When the OS metrics were last updated before the
                calculation and after it, and whether it wrote or deleted any record.

        Raises:
            Exception: If any error occurs while calculating the OS metrics.
        """
        try:
            previous_updated_at = self._get_stored_os_metrics_state().get("updated_at")

            changed_ids: List[str] = []
            self._calculate_os_metrics(wait_for_rebuild=True, changed_ids=changed_ids)

            latest_updated_at = self._get_stored_os_metrics_state().get("updated_at")

            return previous_updated_at, latest_updated_at, bool(changed_ids)

        except Exception as e:
            log_error(f"Error calculating OS metrics: {str(e)}")
            raise e

    def _calculate_os_metrics(
        self, wait_for_rebuild: bool, changed_ids: Optional[List[str]] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Calculate OS metrics for all dates without complete OS metrics.

        Args:
            wait_for_rebuild (bool): Wait for a rebuild another process is running. When False, skip instead.
            changed_ids (Optional[List[str]]): When given, the IDs of the records deleted and of the calculated
                records written are added to it.

        Returns:
            Optional[List[Dict[str, Any]]]: The calculated OS metrics.
        """
        # Stamp first so failed runs are throttled too instead of retried on every read
        self._os_metrics_refreshed_at = time.time()

        lock_token = self._acquire_os_metrics_lock(wait_for_rebuild)
        if lock_token is None:
            # Reset the throttle so the next read tries again
            self._os_metrics_refreshed_at = 0.0
            log_debug("Another process is calculating OS metrics. Won't calculate OS metrics.")
            return None

        try:
            today = datetime.now(timezone.utc).date()

            # The ID of a total record starts with its day
            total_days = [
                os_metrics_record_day(record_id)
                for record_id in self._get_os_metrics_record_ids("aggregation_period", ["daily_total"])[0]
            ]
            latest_completed = max((day for day in total_days if day is not None), default=None)

            days_after_latest_completed: List[date] = []
            if latest_completed is not None:
                days_after_latest_completed = [
                    latest_completed + timedelta(days=offset) for offset in range(1, (today - latest_completed).days)
                ]
            else:
                index_prefix = generate_index_key(self.db_prefix, "os_metrics", "date", "")
                for key in get_all_keys_for_table(
                    valkey_client=self.valkey_client, prefix=self.db_prefix, table_type="os_metrics:index:date"
                ):
                    index_day = os_metrics_record_day(key[len(index_prefix) :])
                    if index_day is not None and index_day < today:
                        days_after_latest_completed.append(index_day)
            open_days = [
                day
                for day, record_ids in zip(
                    days_after_latest_completed,
                    self._get_os_metrics_record_ids("date", [day.isoformat() for day in days_after_latest_completed]),
                )
                if record_ids
            ]
            starting_date = metrics_starting_date_from_days(latest_completed, min(open_days) if open_days else None)

            # Without a completed day every session and run is read: the first session is the day to start from
            start_timestamp = 0
            if latest_completed is not None:
                first_day = latest_completed + timedelta(days=1)
                start_timestamp = int(
                    datetime.combine(first_day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
                )
            end_timestamp = int(
                datetime.combine(today + timedelta(days=1), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            sessions_by_day = self._get_records_for_os_metrics_calculation(
                "sessions", start_timestamp, end_timestamp, lock_token
            )
            if starting_date is None:
                # The records of today are still deleted once its last session is
                if not sessions_by_day and not self._get_os_metrics_record_ids("date", [today.isoformat()])[0]:
                    log_info("No session data found. Won't calculate OS metrics.")
                    return None
                starting_date = min(sessions_by_day, default=today)
            runs_by_day = self._get_records_for_os_metrics_calculation(
                "runs", start_timestamp, end_timestamp, lock_token
            )

            days_to_complete = sorted(
                {day for day in [*runs_by_day, *sessions_by_day, *open_days] if starting_date <= day < today}
            )
            # Today comes first, so a long first rebuild shows the current day early
            dates_to_process = [today, *days_to_complete]

            state = self._get_stored_os_metrics_state()
            updated_at = int(time.time())
            # A rebuild that saved records and not the state left its mark, so the state moves for it
            if state.get("rebuilding"):
                state = build_os_metrics_state(state, updated_at, [], [])
                self.valkey_client.set(self._os_metrics_state_key(), serialize_data(state))

            results = []
            for date_to_process in dates_to_process:
                # A rebuild that lost the lock stops: the process that holds it calculates the days left
                if not self._extend_os_metrics_lock(lock_token):
                    log_debug("Another process is calculating OS metrics. Won't calculate OS metrics.")
                    break

                sessions = sessions_by_day.get(date_to_process, [])
                runs = runs_by_day.get(date_to_process, [])
                stored_rows = self._get_os_metrics_records(
                    self._get_os_metrics_record_ids("date", [date_to_process.isoformat()])[0]
                )
                if sessions or runs or stored_rows:
                    # A nested run also stored as a run of its own is counted from that record
                    stored_run_ids: Set[str] = set()
                    nested_run_ids = sorted(os_metrics_nested_run_ids(runs))
                    for batch_start in range(0, len(nested_run_ids), OS_METRICS_BATCH_SIZE):
                        run_ids = nested_run_ids[batch_start : batch_start + OS_METRICS_BATCH_SIZE]
                        pipeline = self._create_pipeline()
                        for run_id in run_ids:
                            pipeline.exists(
                                [generate_valkey_key(prefix=self.db_prefix, table_type="runs", key_id=run_id)]
                            )
                        stored_run_ids.update(
                            run_id
                            for run_id, exists in zip(run_ids, self._exec_os_metrics_pipeline(pipeline))
                            if exists
                        )

                    records = calculate_date_os_metrics(date_to_process, sessions, runs, stored_run_ids)
                    changed_rows, stale_ids = os_metrics_rows_to_write(records, stored_rows)
                    stored_by_id = {row["id"]: row for row in stored_rows}
                    for record in records:
                        record["id"] = os_metrics_record_id(
                            date_to_process,
                            record["aggregation_period"],
                            record["user_id"],
                            record["agent_id"],
                            record["team_id"],
                            record["workflow_id"],
                            record["parent_id"],
                        )
                        # Update the existing record while preserving created_at
                        if record["id"] in stored_by_id:
                            record["created_at"] = stored_by_id[record["id"]].get("created_at", record["created_at"])
                    if changed_rows or stale_ids:
                        # Each day is written on its own, so a failed day never holds back the days before it
                        # Stamp every record left when the day lost one
                        for row in changed_rows:
                            row["updated_at"] = updated_at
                        previous_state = state
                        state = build_os_metrics_state(state, updated_at, changed_rows, stale_ids, date_to_process)
                        self._store_os_metrics_records(
                            changed_rows, [stored_by_id[stale_id] for stale_id in stale_ids], previous_state, state
                        )
                    results.extend(records)
                    if changed_ids is not None:
                        changed_ids.extend([*stale_ids, *(row["id"] for row in changed_rows)])

            log_debug("Updated OS metrics calculations")

            return results

        finally:
            self._release_os_metrics_lock(lock_token)

    def _get_os_metrics_totals_by_date(
        self, starting_date: date, ending_date: date, user_id: Optional[str], fields: List[str]
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Total the OS metrics of the given date range, every day from one period.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's records. ``None`` totals every owner.
            fields (List[str]): The fields to total.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each day, and when they were last updated.
        """
        days = [starting_date + timedelta(days=offset) for offset in range((ending_date - starting_date).days + 1)]
        if user_id is None:
            records = self._get_os_metrics_records([os_metrics_record_id(day, "daily_total") for day in days])
            total_days = {record["date"] for record in records}
            row_days = [day for day in days if day not in total_days]
            record_ids = self._get_os_metrics_record_ids("date", [day.isoformat() for day in row_days])
            # A total record written since is left out, so no day is counted from two periods
            records.extend(
                record
                for record in self._get_os_metrics_records([record_id for ids in record_ids for record_id in ids])
                if record["aggregation_period"] == "daily"
            )
        else:
            # The ID of each record starts with its day, so only the records of the date range are read
            record_ids = self._get_os_metrics_record_ids("user_id", [user_id])
            records = self._get_os_metrics_records(
                [
                    record_id
                    for record_id in record_ids[0]
                    if starting_date <= (os_metrics_record_day(record_id) or date.min) <= ending_date
                ]
            )
        return total_os_metrics_records(records, fields)

    def get_os_metrics(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Get the OS metrics totals of each day in the given date range.

        OS metrics are refreshed lazily, at most once per minute per process.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's records. ``None`` totals every owner.
            fields (Optional[List[str]]): The fields to total. ``None`` totals all.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each day, and when they were last updated.

        Raises:
            Exception: If any error occurs while getting the OS metrics.
        """
        try:
            fields = resolve_os_metrics_fields(fields)

            # Refresh at most once per minute per process
            if time.time() - self._os_metrics_refreshed_at >= 60:
                try:
                    self._calculate_os_metrics(wait_for_rebuild=False)
                except Exception as e:
                    log_warning(f"Could not refresh OS metrics before reading them: {str(e)}")

            return self._get_os_metrics_totals_by_date(starting_date, ending_date, user_id, fields)

        except Exception as e:
            log_error(f"Error getting OS metrics: {str(e)}")
            raise e

    def get_os_metrics_totals(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], Optional[int]]:
        """Get the OS metrics totals of the whole given date range.

        OS metrics are refreshed lazily, as in get_os_metrics.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's records. ``None`` totals every owner.
            fields (Optional[List[str]]): The fields to total. ``None`` totals all.

        Returns:
            Tuple[Dict[str, Any], Optional[int]]: The totals of the date range, and when they were last updated.

        Raises:
            Exception: If any error occurs while getting the OS metrics totals.
        """
        try:
            fields = resolve_os_metrics_fields(fields)

            if time.time() - self._os_metrics_refreshed_at >= 60:
                try:
                    self._calculate_os_metrics(wait_for_rebuild=False)
                except Exception as e:
                    log_warning(f"Could not refresh OS metrics before reading them: {str(e)}")

            totals, latest_updated_at = self._get_os_metrics_totals_by_date(starting_date, ending_date, user_id, fields)
            return merge_os_metrics_totals(totals, fields), latest_updated_at

        except Exception as e:
            log_error(f"Error getting OS metrics totals: {str(e)}")
            raise e

    def get_os_metrics_state(self, ending_date: Optional[date] = None) -> Tuple[Optional[int], str]:
        """Get when any OS metrics record was last written or deleted, and the hash of the state.

        OS metrics are refreshed lazily, as in get_os_metrics.

        Args:
            ending_date (Optional[date]): The last day that is read. When it is a completed day, the state of
                the records of completed days is returned, which a day still open does not move.

        Returns:
            Tuple[Optional[int], str]: When any record was last written or deleted, and the hash of the state.
                Both are the same again only while no rebuild wrote or deleted a record.

        Raises:
            Exception: If any error occurs while getting the OS metrics state.
        """
        try:
            if time.time() - self._os_metrics_refreshed_at >= 60:
                try:
                    self._calculate_os_metrics(wait_for_rebuild=False)
                except Exception as e:
                    log_warning(f"Could not refresh OS metrics before reading them: {str(e)}")

            # Records expire without a rebuild, which the state cannot tell
            if self.expire is not None:
                return None, ""
            return os_metrics_state_of(self._get_stored_os_metrics_state(), ending_date)

        except Exception as e:
            log_error(f"Error getting OS metrics state: {str(e)}")
            raise e

    # -- Knowledge methods --
    # Valkey stores records as serialized dicts; we filter in Python. A row
    # is visible if its ``user_id`` matches the caller OR is unset. When the
    # caller passes ``user_id=None`` we skip the check entirely.

    @staticmethod
    def _knowledge_doc_is_visible(doc: Dict[str, Any], user_id: Optional[str]) -> bool:
        if user_id is None:
            return True
        owner = doc.get("user_id")
        return owner is None or owner == user_id

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): If provided, only deletes rows owned by this user, not unowned rows.

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
            user_id (Optional[str]): Owner-scoping filter; see module note.

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
            user_id (Optional[str]): Owner-scoping filter; see module note.

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

            # Owner scoping: drop rows the caller isn't allowed to see.
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
        """Create an EvalRunRecord in Valkey.

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
        """Delete an eval run from Valkey.

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
        """Delete multiple eval runs from Valkey using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            eval_run_ids (List[str]): The IDs of the eval runs to delete.
            user_id (Optional[str]): If set, only delete runs owned by this user.

        Raises:
            Exception: If any error occurs while deleting the eval runs.
        """
        if not eval_run_ids:
            return

        if user_id is not None:
            # Filter to this owner's ids up front so the batch below stays one round trip.
            eval_run_ids = [
                eval_run_id
                for eval_run_id in eval_run_ids
                if (self._get_record("evals", eval_run_id) or {}).get("user_id") == user_id
            ]
            if not eval_run_ids:
                return

        try:
            index_fields = ["agent_id", "team_id", "workflow_id", "model_id", "eval_type"]

            # Phase 1: Batch-read all eval runs (needed for index cleanup)
            read_pipeline = self._create_pipeline()
            keys: List[str] = []
            for eval_run_id in eval_run_ids:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="evals", key_id=eval_run_id)
                keys.append(key)
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)

            # Phase 2: Build delete pipeline
            delete_pipeline = self._create_pipeline()
            delete_count = 0

            for i, eval_run_id in enumerate(eval_run_ids):
                raw = read_results[i] if read_results else None
                if raw is None or isinstance(raw, RequestError):
                    continue

                raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                if not raw_str:
                    continue

                record_data = deserialize_data(raw_str)

                if user_id is not None and record_data.get("user_id") != user_id:
                    continue

                # Remove index entries
                for field in index_fields:
                    if field in record_data and record_data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "evals", field, str(record_data[field]))
                        delete_pipeline.srem(index_key, [eval_run_id])

                delete_pipeline.delete([keys[i]])
                delete_count += 1

            if delete_count > 0:
                self._exec_pipeline(delete_pipeline)

            if delete_count == 0:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_debug(f"Deleted {delete_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")
            raise

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from Valkey.

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
        """Get all eval runs from Valkey.

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
                if user_id is not None and run.get("user_id") != user_id:
                    continue

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
        """Update the name of an eval run in Valkey.

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

    def _get_span_stats_for_trace(self, trace_id: str) -> tuple[int, int]:
        """Get total_spans and error_count for a trace using the trace_id index.

        Uses the spans index set to fetch only spans belonging to this trace
        via a single pipeline round trip, instead of scanning all spans.

        Args:
            trace_id: The trace ID to look up spans for.

        Returns:
            tuple[int, int]: (total_spans, error_count)
        """
        index_key = generate_index_key(self.db_prefix, "spans", "trace_id", trace_id)
        span_ids = self.valkey_client.smembers(index_key)
        if not span_ids:
            return 0, 0

        # Pipeline-fetch all span records in one round trip
        pipeline = self._create_pipeline()
        for span_id in span_ids:
            sid = span_id.decode("utf-8") if isinstance(span_id, bytes) else str(span_id)
            key = generate_valkey_key(prefix=self.db_prefix, table_type="spans", key_id=sid)
            pipeline.get(key)

        results = self._exec_pipeline(pipeline)
        if not results:
            return 0, 0

        total = 0
        errors = 0
        for raw in results:
            if raw is None or isinstance(raw, RequestError):
                continue
            total += 1
            data_str: str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else ""
            if data_str:
                span_data = deserialize_data(data_str)
                if span_data.get("status_code") == "ERROR":
                    errors += 1

        return total, errors

    def _enrich_trace_with_span_stats(self, trace_data: Dict[str, Any]) -> None:
        """Add total_spans and error_count to a trace dict in-place."""
        tid = trace_data.get("trace_id", "")
        if tid:
            total_spans, error_count = self._get_span_stats_for_trace(tid)
        else:
            total_spans, error_count = 0, 0
        trace_data["total_spans"] = total_spans
        trace_data["error_count"] = error_count

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
                    self._enrich_trace_with_span_stats(result)
                    return TraceSchema.from_dict(result)
                return None

            elif run_id:
                all_traces = self._get_all_records("traces")
                matching = [t for t in all_traces if t.get("run_id") == run_id]
                if matching:
                    # Sort by start_time descending and get most recent
                    matching.sort(key=lambda x: x.get("start_time", ""), reverse=True)
                    result = matching[0]
                    self._enrich_trace_with_span_stats(result)
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
        filter_expr: Optional[Dict[str, Any]] = None,
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
            filter_expr: Serialized FilterExpr dict to apply on trace fields.

        Returns:
            tuple[List[Trace], int]: Tuple of (list of matching traces, total count).
        """
        try:
            from agno.db.filter_converter import TRACE_COLUMNS
            from agno.tracing.schemas import Trace as TraceSchema

            log_debug(
                f"get_traces called with filters: run_id={run_id}, session_id={session_id}, "
                f"user_id={user_id}, agent_id={agent_id}, page={page}, limit={limit}"
            )

            if filter_expr is not None:
                validate_filter_expr(filter_expr, TRACE_COLUMNS)

            all_traces = self._get_all_records("traces")

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
                if filter_expr is not None and not record_matches_filter_expr(trace, filter_expr, TRACE_COLUMNS):
                    continue

                filtered_traces.append(trace)

            total_count = len(filtered_traces)

            # Sort by start_time descending
            filtered_traces.sort(key=lambda x: x.get("start_time", ""), reverse=True)

            # Apply pagination
            paginated_traces = apply_pagination(records=filtered_traces, limit=limit, page=page)

            # Enrich only the paginated traces with span stats (index-based lookup per trace)
            traces = []
            for row in paginated_traces:
                self._enrich_trace_with_span_stats(row)
                traces.append(TraceSchema.from_dict(row))

            return traces, total_count

        except ValueError:
            # Re-raise ValueError for proper 400 response at the API layer
            raise
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
        filter_expr: Optional[Dict[str, Any]] = None,
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
            filter_expr: Serialized FilterExpr dict to apply on trace fields.
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
            from agno.db.filter_converter import TRACE_COLUMNS

            log_debug(
                f"get_trace_stats called with filters: user_id={user_id}, agent_id={agent_id}, "
                f"workflow_id={workflow_id}, team_id={team_id}, "
                f"start_time={start_time}, end_time={end_time}, page={page}, limit={limit}"
            )

            if filter_expr is not None:
                validate_filter_expr(filter_expr, TRACE_COLUMNS)

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
                if filter_expr is not None and not record_matches_filter_expr(trace, filter_expr, TRACE_COLUMNS):
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

        except ValueError:
            # Re-raise ValueError for proper 400 response at the API layer
            raise
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
        """Create multiple spans in the database using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            spans: List of Span objects to store.
        """
        if not spans:
            return

        try:
            index_fields = ["trace_id", "parent_span_id"]
            pipeline = self._create_pipeline()

            expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
            for span in spans:
                data = span.to_dict()
                key = generate_valkey_key(prefix=self.db_prefix, table_type="spans", key_id=span.span_id)
                pipeline.set(key, serialize_data(data), expiry=expiry)

                for field in index_fields:
                    if field in data and data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "spans", field, str(data[field]))
                        pipeline.sadd(index_key, [span.span_id])

            self._exec_pipeline(pipeline)

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

    # -- Learning methods --

    def _learning_matches(self, record: Dict[str, Any], **filters: Optional[str]) -> bool:
        """Check a learning record against the provided filters. None filters are skipped."""
        return all(record.get(field) == value for field, value in filters.items() if value is not None)

    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a learning record.

        Args:
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).

        Returns:
            Dict with 'content' key containing the learning data, or None.
        """
        try:
            for record in self._get_all_records("learnings"):
                if record.get("learning_type") != learning_type:
                    continue
                if self._learning_matches(
                    record,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    namespace=namespace,
                    entity_id=entity_id,
                    entity_type=entity_type,
                ):
                    return {"content": record.get("content")}
            return None

        except Exception as e:
            log_debug(f"Error retrieving learning: {e}")
            return None

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
        """Insert or update a learning record.

        On update only content, metadata and updated_at change; created_at and
        the identity fields keep their stored values.

        Args:
            id: Unique identifier for the learning.
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            content: The learning content as a dict.
            user_id: Associated user ID.
            agent_id: Associated agent ID.
            team_id: Associated team ID.
            session_id: Associated session ID.
            namespace: Namespace for scoping ('user', 'global', or custom).
            entity_id: Associated entity ID (for entity-specific learnings).
            entity_type: Entity type ('person', 'company', etc.).
            metadata: Optional metadata.
        """
        try:
            current_time = int(time.time())
            existing = self._get_record("learnings", id)

            if existing is not None:
                data = {**existing, "content": content, "metadata": metadata, "updated_at": current_time}
            else:
                data = {
                    "learning_id": id,
                    "learning_type": learning_type,
                    "namespace": namespace,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "team_id": team_id,
                    "session_id": session_id,
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "content": content,
                    "metadata": metadata,
                    "created_at": current_time,
                    "updated_at": current_time,
                }

            self._store_record(
                "learnings",
                id,
                data,
                index_fields=[
                    "learning_type",
                    "namespace",
                    "user_id",
                    "agent_id",
                    "team_id",
                    "session_id",
                    "entity_id",
                    "entity_type",
                ],
            )
            log_debug(f"Upserted learning: {id}")

        except Exception as e:
            log_debug(f"Error upserting learning: {e}")

    def delete_learning(self, id: str) -> bool:
        """Delete a learning record.

        Args:
            id: The learning ID to delete.

        Returns:
            True if deleted, False otherwise.
        """
        try:
            return self._delete_record(
                "learnings",
                id,
                index_fields=[
                    "learning_type",
                    "namespace",
                    "user_id",
                    "agent_id",
                    "team_id",
                    "session_id",
                    "entity_id",
                    "entity_type",
                ],
            )

        except Exception as e:
            log_debug(f"Error deleting learning: {e}")
            return False

    def update_learning(self, id: str, content: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Update an existing learning record in place. Does NOT insert.

        Args:
            id: The learning ID to update.
            content: Replacement content.
            metadata: Replacement metadata.

        Returns:
            True if a record was updated, False if no record with that id exists.
        """
        try:
            existing = self._get_record("learnings", id)
            if existing is None:
                return False

            data = {**existing, "content": content, "metadata": metadata, "updated_at": int(time.time())}
            return self._store_record(
                "learnings",
                id,
                data,
                index_fields=[
                    "learning_type",
                    "namespace",
                    "user_id",
                    "agent_id",
                    "team_id",
                    "session_id",
                    "entity_id",
                    "entity_type",
                ],
            )

        except Exception as e:
            log_error(f"Error updating learning: {e}")
            raise e

    def delete_user_learnings(self, user_id: str, learning_type: Optional[str] = None) -> int:
        """Delete every learning record owned by a user.

        Records with no owner (user_id None) are not affected.

        Args:
            user_id: The user whose learnings should be deleted.
            learning_type: When provided, restrict deletion to this single learning type.

        Returns:
            The number of records deleted.
        """
        try:
            deleted_count = 0
            for record in self._get_all_records("learnings"):
                if record.get("user_id") != user_id:
                    continue
                if learning_type is not None and record.get("learning_type") != learning_type:
                    continue
                record_id = record.get("learning_id")
                if record_id and self._delete_record(
                    "learnings",
                    record_id,
                    index_fields=[
                        "learning_type",
                        "namespace",
                        "user_id",
                        "agent_id",
                        "team_id",
                        "session_id",
                        "entity_id",
                        "entity_type",
                    ],
                ):
                    deleted_count += 1

            return deleted_count

        except Exception as e:
            log_error(f"Error deleting user learnings: {e}")
            raise e

    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get multiple learning records, most recently updated first.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).
            limit: Maximum number of records to return.

        Returns:
            List of learning records.
        """
        try:
            filtered_records = [
                record
                for record in self._get_all_records("learnings")
                if self._learning_matches(
                    record,
                    learning_type=learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    namespace=namespace,
                    entity_id=entity_id,
                    entity_type=entity_type,
                )
            ]

            sorted_records = apply_sorting(records=filtered_records, sort_by="updated_at", sort_order="desc")

            if limit is not None:
                sorted_records = sorted_records[:limit]

            return sorted_records

        except Exception as e:
            log_debug(f"Error getting learnings: {e}")
            return []

    def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Get a learning record by its ID.

        Args:
            id: The learning ID to retrieve.

        Returns:
            The learning record if found, None otherwise.
        """
        try:
            return self._get_record("learnings", id)

        except Exception as e:
            log_error(f"Error getting learning by id: {e}")
            raise e

    def list_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        include_global: bool = False,
        limit: int = 100,
        page: int = 1,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get learning records with filtering, sorting and pagination.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace.
            entity_id: Filter by entity ID.
            entity_type: Filter by entity type.
            include_global: When filtering by user_id, also include unowned records.
            limit: Maximum number of records to return per page.
            page: Page number (1-indexed).
            sort_by: Field to sort by.
            sort_order: Sort order ('asc' or 'desc').

        Returns:
            Tuple of (list of learning records, total count).
        """
        try:
            filtered_records = []
            for record in self._get_all_records("learnings"):
                if user_id is not None:
                    record_user_id = record.get("user_id")
                    if include_global:
                        if record_user_id != user_id and record_user_id is not None:
                            continue
                    elif record_user_id != user_id:
                        continue
                if self._learning_matches(
                    record,
                    learning_type=learning_type,
                    agent_id=agent_id,
                    team_id=team_id,
                    session_id=session_id,
                    namespace=namespace,
                    entity_id=entity_id,
                    entity_type=entity_type,
                ):
                    filtered_records.append(record)

            sorted_records = apply_sorting(
                records=filtered_records, sort_by=sort_by or "updated_at", sort_order=sort_order or "desc"
            )
            paginated_records = apply_pagination(records=sorted_records, limit=limit, page=page)

            return paginated_records, len(filtered_records)

        except Exception as e:
            log_error(f"Error listing learnings: {e}")
            raise e

    def get_learnings_user_stats(
        self,
        learning_type: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get learning statistics grouped by user.

        Args:
            learning_type: Filter by learning type.
            limit: Maximum number of users to return per page.
            page: Page number (1-indexed).
            user_id: Filter by user ID.
            sort_by: Field to sort by ('user_id' or 'last_learning_updated_at').
            sort_order: Sort order ('asc' or 'desc').

        Returns:
            Tuple of (list of user stats dicts, total count).
        """
        try:
            user_stats: Dict[str, Dict[str, Any]] = {}
            for record in self._get_all_records("learnings"):
                if learning_type is not None and record.get("learning_type") != learning_type:
                    continue
                record_user_id = record.get("user_id")
                if user_id is not None:
                    if record_user_id != user_id:
                        continue
                elif record_user_id is None:
                    continue

                updated_at = record.get("updated_at") or 0
                stats = user_stats.get(record_user_id)
                if stats is None or updated_at > (stats["last_learning_updated_at"] or 0):
                    user_stats[record_user_id] = {
                        "user_id": record_user_id,
                        "last_learning_updated_at": updated_at,
                    }

            stats_list = list(user_stats.values())
            reverse = sort_order != "asc"
            if sort_by == "user_id":
                stats_list.sort(key=lambda s: s["user_id"] or "", reverse=reverse)
            else:
                stats_list.sort(key=lambda s: s["last_learning_updated_at"] or 0, reverse=reverse)

            total_count = len(stats_list)
            if limit is not None:
                start = ((page - 1) * limit) if page is not None else 0
                stats_list = stats_list[start : start + limit]

            return stats_list, total_count

        except Exception as e:
            log_error(f"Error getting learning user stats: {e}")
            raise e
