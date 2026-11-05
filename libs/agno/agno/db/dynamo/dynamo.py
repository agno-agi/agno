import json
import time
from datetime import date, datetime, timedelta, timezone
from os import getenv
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Tuple, Union
from uuid import uuid4

from packaging import version as packaging_version

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.dynamo.schemas import get_table_schema_definition
from agno.db.dynamo.utils import (
    aggregate_metrics_key,
    aggregate_metrics_period_user_id,
    apply_pagination,
    apply_sorting,
    batch_get_with_retry,
    batch_write_with_retry,
    build_query_filter_expression,
    build_topic_filter_expression,
    component_metrics_record_id,
    create_table_if_not_exists,
    deserialize_from_dynamodb_item,
    deserialize_knowledge_row,
    deserialize_metrics_date,
    deserialize_metrics_row,
    deserialize_session_result,
    execute_query_with_pagination,
    heartbeat_metrics_refresh_update,
    merge_with_existing_session,
    prepare_session_data,
    query_all_items,
    reopen_metrics_day,
    reopen_metrics_days_from,
    reopen_metrics_month,
    reopen_metrics_row,
    serialize_aggregate_metrics_row,
    serialize_component_metrics_row,
    serialize_eval_record,
    serialize_knowledge_row,
    serialize_to_dynamo_item,
)
from agno.db.migrations.manager import MigrationManager
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import (
    AGGREGATE_METRICS_COUNT_COLUMNS,
    AGGREGATE_METRICS_ROWS_FIELDS,
    METRICS_BY_OWNER_FIELDS,
    METRICS_COMPONENT_TYPES,
    METRICS_LOCK_SECONDS,
    METRICS_REFRESH_ID,
    METRICS_STOPPED_ERROR,
    METRICS_WRITE_RETRIES,
    add_metrics_month_totals,
    aggregate_metrics_row_to_store,
    aggregate_metrics_rows_to_write,
    build_aggregate_metrics_month_rows,
    build_aggregate_metrics_rows,
    build_metrics_by_owner_from_rows,
    build_metrics_from_aggregate_metrics,
    build_single_run_row,
    calculate_date_component_metrics,
    component_metrics_rows_to_write,
    database_error_message,
    deserialize_metrics_refresh_row,
    deserialize_run,
    deserialize_session,
    deserialize_sessions,
    drop_legacy_metrics,
    filter_context_runs,
    get_metrics_fingerprint,
    get_metrics_legacy_runs,
    get_metrics_reopen_session_ids,
    get_months_to_calculate_metrics_for,
    list_metrics_totals_models,
    merge_metrics_totals,
    merge_runs_table_with_legacy_blob,
    metrics_day_completed,
    metrics_day_ranges,
    metrics_day_to_reopen,
    metrics_days_since_last_calculation,
    metrics_full_months,
    metrics_month_end,
    metrics_nested_run_ids,
    metrics_refresh_status,
    metrics_remote_member_team_session_ids,
    metrics_rows_fields,
    metrics_versions,
    resolve_metrics_fields,
    total_metrics_rows,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import Session
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    import boto3  # type: ignore[import-untyped]
except ImportError:
    raise ImportError("`boto3` not installed. Please install it using `pip install boto3`")


# DynamoDB batch_write_item has a hard limit of 25 items per request
DYNAMO_BATCH_SIZE_LIMIT = 25

# DynamoDB batch_get_item has a hard limit of 100 keys per request
DYNAMO_BATCH_GET_SIZE_LIMIT = 100


class DynamoDb(BaseDb):
    def __init__(
        self,
        db_client=None,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        session_table: Optional[str] = None,
        runs_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        component_metrics_table: Optional[str] = None,
        aggregate_metrics_table: Optional[str] = None,
        metrics_refreshes_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a DynamoDB database.

        Args:
            db_client: The DynamoDB client to use.
            region_name: AWS region name.
            aws_access_key_id: AWS access key ID.
            aws_secret_access_key: AWS secret access key.
            session_table: The name of the session table.
            memory_table: The name of the memory table.
            metrics_table: The name of the metrics table.
            component_metrics_table: The name of the table to store the metrics of each agent, team and workflow.
            aggregate_metrics_table: The name of the table to store the metrics of each user.
            metrics_refreshes_table: The name of the metrics refreshes table.
            eval_table: The name of the eval table.
            knowledge_table: The name of the knowledge table.
            traces_table: The name of the traces table.
            spans_table: The name of the spans table.
            id: ID of the database.
        """
        if id is None:
            seed = str(db_client) if db_client else f"{region_name}_{aws_access_key_id}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            runs_table=runs_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            component_metrics_table=component_metrics_table,
            aggregate_metrics_table=aggregate_metrics_table,
            metrics_refreshes_table=metrics_refreshes_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
        )

        if metrics_table is not None:
            log_warning("metrics_table is deprecated; use component_metrics_table and aggregate_metrics_table.")

        if db_client is not None:
            self.client = db_client
        else:
            if not region_name and not getenv("AWS_REGION"):
                raise ValueError("AWS_REGION is not set. Please set the AWS_REGION environment variable.")
            if not aws_access_key_id and not getenv("AWS_ACCESS_KEY_ID"):
                raise ValueError("AWS_ACCESS_KEY_ID is not set. Please set the AWS_ACCESS_KEY_ID environment variable.")
            if not aws_secret_access_key and not getenv("AWS_SECRET_ACCESS_KEY"):
                raise ValueError(
                    "AWS_SECRET_ACCESS_KEY is not set. Please set the AWS_SECRET_ACCESS_KEY environment variable."
                )

            session_kwargs = {}
            session_kwargs["region_name"] = region_name or getenv("AWS_REGION")
            session_kwargs["aws_access_key_id"] = aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")

            session = boto3.Session(**session_kwargs)
            self.client = session.client("dynamodb")

        # The days whose metrics a write could not reopen, retried by the next write
        self._metrics_days_not_reopened: Set[date] = set()
        # Whether a session holds legacy runs, None until a read of every session found out
        self._metrics_legacy_runs: Optional[bool] = None

    def table_exists(self, table_name: str) -> bool:
        """Check if a DynamoDB table exists.

        Args:
            table_name: The name of the table to check

        Returns:
            bool: True if the table exists, False otherwise
        """
        try:
            self.client.describe_table(TableName=table_name)
            return True
        except self.client.exceptions.ResourceNotFoundException:
            return False

    def _create_all_tables(self):
        """Create all configured DynamoDB tables if they don't exist."""
        tables_to_create = [
            ("sessions", self.session_table_name),
            ("runs", self.runs_table_name),
            ("memories", self.memory_table_name),
            ("metrics", self.metrics_table_name),
            ("component_metrics", self.component_metrics_table_name),
            ("aggregate_metrics", self.aggregate_metrics_table_name),
            ("metrics_refreshes", self.metrics_refreshes_table_name),
            ("evals", self.eval_table_name),
            ("knowledge", self.knowledge_table_name),
        ]

        for table_type, table_name in tables_to_create:
            if not self.table_exists(table_name):
                schema = get_table_schema_definition(table_type)
                schema["TableName"] = table_name
                create_table_if_not_exists(self.client, table_name, schema)
                # Store the schema version for the created sessions table, which holds no legacy runs for metrics
                if table_type == "sessions":
                    latest_schema_version = MigrationManager(self).latest_schema_version
                    self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = True) -> Optional[str]:
        """
        Get table name and ensure the table exists, creating it if needed.

        Args:
            table_type: Type of table ("sessions", "memories", "metrics", "component_metrics", "aggregate_metrics",
                "metrics_refreshes", "evals", "knowledge", "traces", "spans")

        Returns:
            str: The table name

        Raises:
            ValueError: If table name is not configured or table type is unknown
        """
        table_name = None

        if table_type == "sessions":
            table_name = self.session_table_name
        elif table_type == "runs":
            table_name = self.runs_table_name
        elif table_type == "memories":
            table_name = self.memory_table_name
        elif table_type == "metrics":
            table_name = self.metrics_table_name
        elif table_type == "component_metrics":
            table_name = self.component_metrics_table_name
        elif table_type == "aggregate_metrics":
            table_name = self.aggregate_metrics_table_name
        elif table_type == "metrics_refreshes":
            table_name = self.metrics_refreshes_table_name
        elif table_type == "evals":
            table_name = self.eval_table_name
        elif table_type == "knowledge":
            table_name = self.knowledge_table_name
        elif table_type == "traces":
            table_name = self.trace_table_name
        elif table_type == "spans":
            # Ensure traces table exists first (spans reference traces)
            self._get_table("traces", create_table_if_not_found=True)
            table_name = self.span_table_name
        else:
            raise ValueError(f"Unknown table type: {table_type}")

        # Check if table exists, create if it doesn't
        if not self.table_exists(table_name) and create_table_if_not_found:
            schema = get_table_schema_definition(table_type)
            schema["TableName"] = table_name
            create_table_if_not_exists(self.client, table_name, schema)
            # Store the schema version for the created sessions table, which holds no legacy runs for metrics
            if table_type == "sessions":
                latest_schema_version = MigrationManager(self).latest_schema_version
                self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

        return table_name

    def _ensure_schema_versions_table(self) -> None:
        from agno.db.dynamo.schemas import SCHEMA_VERSIONS_TABLE_SCHEMA
        from agno.db.dynamo.utils import create_table_if_not_exists

        schema = SCHEMA_VERSIONS_TABLE_SCHEMA.copy()
        schema["TableName"] = self.versions_table_name
        create_table_if_not_exists(self.client, self.versions_table_name, schema)

    def get_latest_schema_version(self, table_name: str = "") -> Optional[str]:
        """Get the schema version stamped for the given table.

        Defaults to "2.0.0" when nothing is stamped so the MigrationManager
        runs migrations instead of skipping the table.
        """
        self._ensure_schema_versions_table()
        response = self.client.get_item(
            TableName=self.versions_table_name,
            Key={"table_name": {"S": table_name}},
        )
        item = response.get("Item")
        if not item:
            return "2.0.0"
        return item.get("version", {}).get("S") or "2.0.0"

    def upsert_schema_version(self, table_name: str = "", version: str = "") -> None:
        """Record the schema version stamp for the given table."""
        self._ensure_schema_versions_table()
        self.client.put_item(
            TableName=self.versions_table_name,
            Item={
                "table_name": {"S": table_name},
                "version": {"S": version},
                "updated_at": {"N": str(int(time.time()))},
            },
        )

    # --- Runs ---

    def _query_runs_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Query all run items for a session, ordered by created_at via the GSI."""
        table_name = self._get_table("runs", create_table_if_not_found=False)
        items: List[Dict[str, Any]] = []
        try:
            response = self.client.query(
                TableName=table_name,
                IndexName="session_id-created_at-index",
                KeyConditionExpression="session_id = :sid",
                ExpressionAttributeValues={":sid": {"S": session_id}},
            )
            items.extend(response.get("Items", []))
            while "LastEvaluatedKey" in response:
                response = self.client.query(
                    TableName=table_name,
                    IndexName="session_id-created_at-index",
                    KeyConditionExpression="session_id = :sid",
                    ExpressionAttributeValues={":sid": {"S": session_id}},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))
        except self.client.exceptions.ResourceNotFoundException:
            return []
        return items

    def _get_session_runs_data(self, session_id: str) -> List[Dict[str, Any]]:
        """Return raw run_data dicts for a session, ordered by run_index then created_at."""
        items = self._query_runs_by_session(session_id)
        rows = [deserialize_from_dynamodb_item(it) for it in items]
        rows.sort(key=lambda r: (r.get("run_index") or 0, r.get("created_at") or 0))
        return [r["run_data"] for r in rows if "run_data" in r]

    def _get_sessions_runs(self, session_ids: List[str]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """Run dicts for several sessions in one read, used by the search fallback."""
        return self._get_sessions_runs_data(session_ids)

    def _get_sessions_runs_data(self, session_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        if not session_ids:
            return {}
        if len(session_ids) == 1:
            return {session_ids[0]: self._get_session_runs_data(session_ids[0])}
        from concurrent.futures import ThreadPoolExecutor

        # Runs are partitioned by session_id in the GSI, so each session needs its own Query; run them concurrently.
        with ThreadPoolExecutor(max_workers=min(len(session_ids), 16)) as pool:
            return dict(zip(session_ids, pool.map(self._get_session_runs_data, session_ids)))

    def upsert_run(
        self,
        run: Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]],
        session_id: str,
        user_id: Optional[str] = None,
        run_index: Optional[int] = None,
    ) -> None:
        """Upsert a single run item into the runs table (O(1) operation).

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
            table_name = self._get_table("runs", create_table_if_not_found=True)
            if table_name is None:
                return

            row = build_single_run_row(
                run=run,
                session_id=session_id,
                user_id=user_id,
                run_index=run_index,
            )

            # Preserve the original run_index if the item already exists
            try:
                existing_resp = self.client.get_item(TableName=table_name, Key={"run_id": {"S": row["run_id"]}})
                existing_item = existing_resp.get("Item")
                if existing_item:
                    existing = deserialize_from_dynamodb_item(existing_item)
                    if "run_index" in existing:
                        row["run_index"] = existing["run_index"]
                    # The stored created_at, which a resumed run keeps
                    if existing.get("created_at") is not None:
                        row["created_at"] = existing["created_at"]
            except self.client.exceptions.ResourceNotFoundException:
                pass

            payload = {k: v for k, v in row.items() if v is not None}
            if "run_data" in payload and isinstance(payload["run_data"], (dict, list)):
                payload["run_data"] = json.dumps(payload["run_data"])
            item = serialize_to_dynamo_item(payload)
            self.client.put_item(TableName=table_name, Item=item)
            self._reopen_metrics_days([row["created_at"]])
        except Exception as e:
            log_error(f"Exception upserting run into runs table: {str(e)}")
            raise e

    def _delete_session_runs(self, session_id: str) -> int:
        """Cascade-delete every run row for a session."""
        items = self._query_runs_by_session(session_id)
        if not items:
            return 0
        table_name = self._get_table("runs", create_table_if_not_found=False)
        run_ids = [it.get("run_id", {}).get("S") for it in items]
        run_ids = [r for r in run_ids if r]
        for i in range(0, len(run_ids), DYNAMO_BATCH_SIZE_LIMIT):
            batch = run_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]
            delete_requests = [{"DeleteRequest": {"Key": {"run_id": {"S": rid}}}} for rid in batch]
            batch_write_with_retry(self.client, {table_name: delete_requests})
        return len(run_ids)

    def cleanup_legacy_runs_field(self, force: bool = False) -> bool:
        """Unset the legacy ``runs`` attribute on every session item.

        The v3.0.0 migration intentionally leaves the legacy ``runs`` field as a
        backup. Once verified, call this to reclaim the storage.

        Args:
            force: If True, unset the field even on sessions that still hold a
                non-null ``runs`` blob. Defaults to False.

        Returns:
            True if any session items were touched.
        """
        table_name = self._get_table("sessions", create_table_if_not_found=False)
        items: List[Dict[str, Any]] = []
        try:
            response = self.client.scan(TableName=table_name)
            items.extend(response.get("Items", []))
            while "LastEvaluatedKey" in response:
                response = self.client.scan(TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response.get("Items", []))
        except self.client.exceptions.ResourceNotFoundException:
            return False

        if not items:
            return False

        if not force:
            pending = 0
            for it in items:
                runs_attr = it.get("runs")
                if runs_attr is None:
                    continue
                # Treat empty list/string as "no legacy data"
                if "S" in runs_attr:
                    try:
                        decoded = json.loads(runs_attr["S"])
                        if decoded:
                            pending += 1
                    except (json.JSONDecodeError, TypeError):
                        if runs_attr["S"]:
                            pending += 1
                elif "L" in runs_attr and runs_attr["L"]:
                    pending += 1
            if pending:
                raise RuntimeError(
                    f"Refusing to unset {table_name}.runs: {pending} session(s) still have "
                    "non-null `runs` content. Run MigrationManager(db).up() first, or pass force=True."
                )

        touched = 0
        for it in items:
            if "runs" not in it:
                continue
            session_id = it.get("session_id", {}).get("S")
            if not session_id:
                continue
            try:
                self.client.update_item(
                    TableName=table_name,
                    Key={"session_id": {"S": session_id}},
                    UpdateExpression="REMOVE #runs",
                    ExpressionAttributeNames={"#runs": "runs"},
                )
                touched += 1
            except Exception as e:
                log_error(f"Failed to unset runs on session {session_id}: {str(e)}")
        log_info(f"Unset runs on {touched} session item(s)")
        return touched > 0

    def get_run(
        self, run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]]]:
        try:
            table_name = self._get_table("runs", create_table_if_not_found=False)
            response = self.client.get_item(TableName=table_name, Key={"run_id": {"S": run_id}})
            item = response.get("Item")
            if not item:
                return None
            row = deserialize_from_dynamodb_item(item)
            if not deserialize:
                return row
            return deserialize_run(row.get("run_type"), row["run_data"])
        except self.client.exceptions.ResourceNotFoundException:
            return None
        except Exception as e:
            log_error(f"Error reading run {run_id}: {str(e)}")
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
        try:
            table_name = self._get_table("runs", create_table_if_not_found=False)
            items: List[Dict[str, Any]] = []
            try:
                if session_id is not None:
                    items = self._query_runs_by_session(session_id)
                else:
                    response = self.client.scan(TableName=table_name)
                    items.extend(response.get("Items", []))
                    while "LastEvaluatedKey" in response:
                        response = self.client.scan(
                            TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"]
                        )
                        items.extend(response.get("Items", []))
            except self.client.exceptions.ResourceNotFoundException:
                items = []

            rows = [deserialize_from_dynamodb_item(it) for it in items]

            if user_id is not None:
                rows = [r for r in rows if r.get("user_id") == user_id]
            if agent_id is not None:
                rows = [r for r in rows if r.get("agent_id") == agent_id]
            if team_id is not None:
                rows = [r for r in rows if r.get("team_id") == team_id]
            if workflow_id is not None:
                rows = [r for r in rows if r.get("workflow_id") == workflow_id]
            if status is not None:
                status_value = status.value if isinstance(status, RunStatus) else status
                rows = [r for r in rows if r.get("status") == status_value]

            total_count = len(rows)

            if sort_by is not None:
                rows = apply_sorting(rows, sort_by, sort_order)
            else:
                rows = sorted(rows, key=lambda r: (r.get("run_index") or 0, r.get("created_at") or 0))

            if limit is not None:
                rows = apply_pagination(rows, limit, page)

            if not deserialize:
                return rows, total_count
            return [deserialize_run(r.get("run_type"), r["run_data"]) for r in rows]
        except Exception as e:
            log_error(f"Error reading runs: {str(e)}")
            raise e

    def _scrub_run_ids_from_session_legacy_blob(self, session_id: str, run_ids: set) -> None:
        """Remove ``run_ids`` from the given session's legacy ``runs`` field.

        Partial-migration hygiene: v3 copied runs into their own table but
        preserved the session item's ``runs`` attribute as backup. Deleting
        the run item alone leaves that attribute intact, and the read path's
        ``merge_runs_table_with_legacy_blob`` resurrects the ghost.
        """
        if not run_ids or not session_id:
            return
        try:
            sessions_table = self._get_table("sessions", create_table_if_not_found=False)
            resp = self.client.get_item(TableName=sessions_table, Key={"session_id": {"S": session_id}})
            item = resp.get("Item")
            if not item:
                return
            session = deserialize_from_dynamodb_item(item)
            legacy = session.get("runs")
            if not isinstance(legacy, list):
                return
            kept = [r for r in legacy if not (isinstance(r, dict) and r.get("run_id") in run_ids)]
            if len(kept) == len(legacy):
                return
            session["runs"] = kept
            self.client.put_item(TableName=sessions_table, Item=serialize_to_dynamo_item(session))
        except Exception:
            log_debug("legacy-runs scrub failed; primary delete still succeeded", exc_info=True)

    def delete_run(self, run_id: str) -> bool:
        try:
            table_name = self._get_table("runs", create_table_if_not_found=False)
            # Fetch session_id before deletion so we can scrub the legacy blob.
            sid: Optional[str] = None
            try:
                snap = self.client.get_item(TableName=table_name, Key={"run_id": {"S": run_id}})
                if snap.get("Item"):
                    sid = deserialize_from_dynamodb_item(snap["Item"]).get("session_id")
            except Exception:
                pass
            self.client.delete_item(
                TableName=table_name,
                Key={"run_id": {"S": run_id}},
                ConditionExpression="attribute_exists(run_id)",
            )
            if sid:
                self._scrub_run_ids_from_session_legacy_blob(sid, {run_id})
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        except self.client.exceptions.ResourceNotFoundException:
            return False
        except Exception as e:
            log_error(f"Error deleting run {run_id}: {str(e)}")
            raise e

    def delete_runs(self, run_ids: List[str]) -> None:
        if not run_ids:
            return
        try:
            table_name = self._get_table("runs", create_table_if_not_found=False)
            # Pre-fetch session_id → run_ids mapping for legacy-blob scrub.
            runs_by_session: Dict[str, set] = {}
            for rid in run_ids:
                try:
                    snap = self.client.get_item(TableName=table_name, Key={"run_id": {"S": rid}})
                    if snap.get("Item"):
                        sid = deserialize_from_dynamodb_item(snap["Item"]).get("session_id")
                        if sid:
                            runs_by_session.setdefault(sid, set()).add(rid)
                except Exception:
                    pass

            for i in range(0, len(run_ids), DYNAMO_BATCH_SIZE_LIMIT):
                batch = run_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]
                delete_requests = [{"DeleteRequest": {"Key": {"run_id": {"S": rid}}}} for rid in batch]
                batch_write_with_retry(self.client, {table_name: delete_requests})

            for sid, rids in runs_by_session.items():
                self._scrub_run_ids_from_session_legacy_blob(sid, rids)
        except self.client.exceptions.ResourceNotFoundException:
            return
        except Exception as e:
            log_error(f"Error deleting runs: {str(e)}")
            raise e

    # --- Sessions ---

    def delete_session(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> bool:
        """
        Delete a session from the database.

        Args:
            session_id: The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the session.
        """
        if not session_id:
            return False

        try:
            kwargs: Dict[str, Any] = {
                "TableName": self.session_table_name,
                "Key": {"session_id": {"S": session_id}},
            }
            if user_id is not None:
                kwargs["ConditionExpression"] = "user_id = :user_id"
                kwargs["ExpressionAttributeValues"] = {":user_id": {"S": user_id}}
            self.client.delete_item(**kwargs)
            # Cascade-delete runs for this session
            try:
                self._delete_session_runs(session_id)
            except Exception as e:
                log_error(f"Failed to cascade-delete runs for session {session_id}: {str(e)}")
            return True

        except self.client.exceptions.ConditionalCheckFailedException:
            log_debug(f"No session found to delete with session_id: {session_id} and user_id: {user_id}")
            return False

        except Exception as e:
            log_error(f"Failed to delete session {session_id}: {str(e)}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """
        Delete sessions from the database in batches.

        Args:
            session_ids: List of session IDs to delete
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the sessions.
        """
        if not session_ids or not self.session_table_name:
            return

        try:
            if user_id is not None:
                for session_id in session_ids:
                    try:
                        self.client.delete_item(
                            TableName=self.session_table_name,
                            Key={"session_id": {"S": session_id}},
                            ConditionExpression="user_id = :user_id",
                            ExpressionAttributeValues={":user_id": {"S": user_id}},
                        )
                    except self.client.exceptions.ConditionalCheckFailedException:
                        pass
            else:
                for i in range(0, len(session_ids), DYNAMO_BATCH_SIZE_LIMIT):
                    batch = session_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]
                    delete_requests = []

                    for session_id in batch:
                        delete_requests.append({"DeleteRequest": {"Key": {"session_id": {"S": session_id}}}})

                    if delete_requests:
                        batch_write_with_retry(self.client, {self.session_table_name: delete_requests})

            # Cascade-delete runs for each session
            for session_id in session_ids:
                try:
                    self._delete_session_runs(session_id)
                except Exception as e:
                    log_error(f"Failed to cascade-delete runs for session {session_id}: {str(e)}")

        except Exception as e:
            log_error(f"Failed to delete sessions: {str(e)}")
            raise e

    def get_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
        runs_limit: Optional[int] = None,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Get a session from the database as a Session object.

        Args:
            session_id (str): The ID of the session to get.
            session_type (Optional[SessionType]): The type of session to get. If None, the type is inferred.
            user_id (Optional[str]): The ID of the user to get the session for.
            deserialize (Optional[bool]): Whether to deserialize the session.

        Returns:
            Optional[Session]: The session data as a Session object.

        Raises:
            Exception: If any error occurs while getting the session.
        """
        try:
            table_name = self._get_table("sessions")
            response = self.client.get_item(
                TableName=table_name,
                Key={"session_id": {"S": session_id}},
            )

            item = response.get("Item")
            if not item:
                return None

            session = deserialize_from_dynamodb_item(item)

            if user_id is not None and session.get("user_id") != user_id:
                return None

            if not session:
                return None

            # Attach runs from the runs table, merged with any legacy `runs` field
            try:
                runs_data = self._get_session_runs_data(session_id)
                session["runs"] = merge_runs_table_with_legacy_blob(runs_data, session.get("runs"))
                if runs_limit is not None:
                    # No query engine to push "last N" down: filter+slice in memory to
                    # match the SQL fast path (drop member/skip-status runs, then last N).
                    session["runs"] = filter_context_runs(session["runs"] or [])[-runs_limit:]
            except Exception as e:
                log_error(f"Failed to load runs for session {session_id}: {str(e)}")

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Failed to get session {session_id}: {str(e)}")
            raise e

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
        include_runs: bool = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        try:
            table_name = self._get_table("sessions")
            if table_name is None:
                return [] if deserialize else ([], 0)

            # Build filter parts (non-key filters used by both query and scan)
            non_key_filters: List[str] = []
            expression_attribute_names: Dict[str, str] = {}
            expression_attribute_values: Dict[str, Any] = {}

            if user_id is not None:
                non_key_filters.append("#user_id = :user_id")
                expression_attribute_names["#user_id"] = "user_id"
                expression_attribute_values[":user_id"] = {"S": user_id}

            if component_id:
                if session_type == SessionType.AGENT:
                    non_key_filters.append("#agent_id = :component_id")
                    expression_attribute_names["#agent_id"] = "agent_id"
                elif session_type == SessionType.TEAM:
                    non_key_filters.append("#team_id = :component_id")
                    expression_attribute_names["#team_id"] = "team_id"
                elif session_type == SessionType.WORKFLOW:
                    non_key_filters.append("#workflow_id = :component_id")
                    expression_attribute_names["#workflow_id"] = "workflow_id"
                elif session_type is None:
                    non_key_filters.append(
                        "(#agent_id = :component_id OR #team_id = :component_id OR #workflow_id = :component_id)"
                    )
                    expression_attribute_names["#agent_id"] = "agent_id"
                    expression_attribute_names["#team_id"] = "team_id"
                    expression_attribute_names["#workflow_id"] = "workflow_id"
                expression_attribute_values[":component_id"] = {"S": component_id}

            # Build timestamp conditions separately: they go into KeyConditionExpression
            # when querying the session_type-created_at-index GSI (created_at is the range key),
            # but into FilterExpression when scanning the base table.
            #
            # DynamoDB only allows one condition per key in KeyConditionExpression, so when
            # both start and end are provided we must use BETWEEN instead of two separate conditions.
            has_start = start_timestamp is not None
            has_end = end_timestamp is not None

            if has_start or has_end:
                expression_attribute_names["#created_at"] = "created_at"

            if has_start:
                expression_attribute_values[":start_ts"] = {"N": str(start_timestamp)}
            if has_end:
                expression_attribute_values[":end_ts"] = {"N": str(end_timestamp)}

            # For the scan path, individual conditions are fine (no key constraint).
            scan_timestamp_conditions: List[str] = []
            if has_start:
                scan_timestamp_conditions.append("#created_at >= :start_ts")
            if has_end:
                scan_timestamp_conditions.append("#created_at <= :end_ts")

            # For the query path (GSI), build a single key range condition.
            if has_start and has_end:
                key_range_condition = "#created_at BETWEEN :start_ts AND :end_ts"
            elif has_start:
                key_range_condition = "#created_at >= :start_ts"
            elif has_end:
                key_range_condition = "#created_at <= :end_ts"
            else:
                key_range_condition = None

            items = []
            if session_type is not None:
                expression_attribute_values[":session_type"] = {"S": session_type.value}

                # When querying session_type-created_at-index, created_at is the range key
                # and must be part of KeyConditionExpression, not FilterExpression.
                key_condition = "session_type = :session_type"
                if key_range_condition:
                    key_condition += " AND " + key_range_condition

                query_kwargs: Dict[str, Any] = {
                    "TableName": table_name,
                    "IndexName": "session_type-created_at-index",
                    "KeyConditionExpression": key_condition,
                    "ExpressionAttributeValues": expression_attribute_values,
                }
                if non_key_filters:
                    query_kwargs["FilterExpression"] = " AND ".join(non_key_filters)
                if expression_attribute_names:
                    query_kwargs["ExpressionAttributeNames"] = expression_attribute_names

                if sort_by == "created_at":
                    query_kwargs["ScanIndexForward"] = sort_order != "desc"

                if limit and not page:
                    query_kwargs["Limit"] = limit

                response = self.client.query(**query_kwargs)
                items.extend(response.get("Items", []))

                # Handle query pagination
                while "LastEvaluatedKey" in response:
                    query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.query(**query_kwargs)
                    items.extend(response.get("Items", []))
            else:
                # For scan, timestamp conditions go into FilterExpression
                # (created_at is not a key attribute on the base table).
                all_scan_filters = non_key_filters + scan_timestamp_conditions
                scan_kwargs: Dict[str, Any] = {"TableName": table_name}
                if all_scan_filters:
                    scan_kwargs["FilterExpression"] = " AND ".join(all_scan_filters)
                if expression_attribute_names:
                    scan_kwargs["ExpressionAttributeNames"] = expression_attribute_names
                if expression_attribute_values:
                    scan_kwargs["ExpressionAttributeValues"] = expression_attribute_values
                if limit and not page:
                    scan_kwargs["Limit"] = limit

                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

                # Handle scan pagination
                while "LastEvaluatedKey" in response:
                    scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.scan(**scan_kwargs)
                    items.extend(response.get("Items", []))

            # Convert DynamoDB items to session data
            sessions_data = []
            for item in items:
                session_data = deserialize_from_dynamodb_item(item)
                if session_data:
                    sessions_data.append(session_data)

            # Search scans skip the runs table; the record's legacy runs field is kept for merging later.
            # Attach runs from the runs table, merged with legacy blob
            if include_runs and sessions_data:
                try:
                    runs_by_session = self._get_sessions_runs_data([s["session_id"] for s in sessions_data])
                    for s in sessions_data:
                        s["runs"] = merge_runs_table_with_legacy_blob(
                            runs_by_session.get(s["session_id"], []), s.get("runs")
                        )
                except Exception as e:
                    log_error(f"Failed to attach runs to sessions: {str(e)}")

            # Filter by session_name in-memory (stored inside session_data JSON)
            if session_name:
                sessions_data = [
                    s
                    for s in sessions_data
                    if session_name.lower() in (s.get("session_data") or {}).get("session_name", "").lower()
                ]

            # Apply in-memory sorting
            if sort_by:
                sessions_data = apply_sorting(sessions_data, sort_by, sort_order)

            # Get total count before pagination
            total_count = len(sessions_data)

            # Apply pagination
            if page:
                sessions_data = apply_pagination(sessions_data, limit, page)

            if not deserialize:
                return sessions_data, total_count

            return deserialize_sessions(session_type, sessions_data)

        except Exception as e:
            log_error(f"Failed to get sessions: {str(e)}")
            raise e

    def rename_session(
        self,
        session_id: str,
        session_type: Optional[SessionType],
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Rename a session in the database.

        Args:
            session_id: The ID of the session to rename.
            session_type: The type of session to rename.
            session_name: The new name for the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Session]: The renamed session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while renaming the session.
        """
        try:
            if not self.session_table_name:
                raise Exception("Sessions table not found")

            # Get current session_data
            get_response = self.client.get_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}},
            )
            current_item = get_response.get("Item")
            if not current_item:
                return None

            # Deserialize the item once and reuse
            item_data = deserialize_from_dynamodb_item(current_item)

            # Verify user_id if provided
            if user_id is not None:
                if item_data.get("user_id") != user_id:
                    return None

            # Update session_data with the new session_name
            session_data = item_data.get("session_data", {})
            session_data["session_name"] = session_name
            attr_values: Dict[str, Any] = {
                ":session_data": {"S": json.dumps(session_data)},
                ":updated_at": {"N": str(int(time.time()))},
            }
            condition_parts: List[str] = []
            if session_type is not None:
                attr_values[":session_type"] = {"S": session_type.value}
                condition_parts.append("session_type = :session_type")
            if user_id is not None:
                condition_parts.append("user_id = :user_id")
                attr_values[":user_id"] = {"S": user_id}

            update_kwargs: Dict[str, Any] = {
                "TableName": self.session_table_name,
                "Key": {"session_id": {"S": session_id}},
                "UpdateExpression": "SET session_data = :session_data, updated_at = :updated_at",
                "ExpressionAttributeValues": attr_values,
                "ReturnValues": "ALL_NEW",
            }
            if condition_parts:
                update_kwargs["ConditionExpression"] = " AND ".join(condition_parts)

            response = self.client.update_item(**update_kwargs)
            item = response.get("Attributes")
            if not item:
                return None

            session = deserialize_from_dynamodb_item(item)

            # Attach runs from the runs table, merged with legacy blob
            try:
                runs_data = self._get_session_runs_data(session_id)
                session["runs"] = merge_runs_table_with_legacy_blob(runs_data, session.get("runs"))
            except Exception as e:
                log_error(f"Failed to load runs for renamed session {session_id}: {str(e)}")

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except self.client.exceptions.ConditionalCheckFailedException:
            log_debug(f"Rename condition not met for session {session_id} (type/user mismatch)")
            return None

        except Exception as e:
            log_error(f"Failed to rename session {session_id}: {str(e)}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Upsert a session into the database.

        This method provides true upsert behavior: creates a new session if it doesn't exist,
        or updates an existing session while preserving important fields.

        Args:
            session (Session): The session to upsert.
            deserialize (Optional[bool]): Whether to deserialize the session.

        Returns:
            Optional[Session]: The upserted session if successful, None otherwise.
        """
        try:
            table_name = self._get_table("sessions", create_table_if_not_found=True)

            # Get session if it already exists in the db.
            # We need to do this to handle updating nested fields.
            response = self.client.get_item(TableName=table_name, Key={"session_id": {"S": session.session_id}})
            existing_item = response.get("Item")

            if existing_item:
                existing_uid = existing_item.get("user_id", {}).get("S")
                if existing_uid is not None and existing_uid != session.user_id:
                    return None

            # Prepare the session to upsert (without the inline `runs` list).
            serialized_session = prepare_session_data(session, include_runs=False)
            if existing_item:
                serialized_session = merge_with_existing_session(serialized_session, existing_item)
                serialized_session["updated_at"] = int(time.time())
            else:
                serialized_session["updated_at"] = serialized_session["created_at"]

            # The legacy `runs` attribute is intentionally preserved: merge_with_existing_session
            # above carries it forward from the existing item, and put_item writes it back as a
            # frozen backup until cleanup_legacy_runs_field() removes it. Dropping it here would
            # lose history for sessions not yet migrated to the runs table.
            item = serialize_to_dynamo_item(serialized_session)
            put_kwargs: Dict[str, Any] = {"TableName": table_name, "Item": item}

            expr_names = {"#uid": "user_id"}
            if session.user_id is not None:
                put_kwargs["ConditionExpression"] = (
                    "attribute_not_exists(session_id) OR #uid = :incoming_uid OR attribute_not_exists(#uid)"
                )
                put_kwargs["ExpressionAttributeValues"] = {":incoming_uid": {"S": session.user_id}}
            else:
                put_kwargs["ConditionExpression"] = "attribute_not_exists(session_id) OR attribute_not_exists(#uid)"
            put_kwargs["ExpressionAttributeNames"] = expr_names

            reopen_session_ids = get_metrics_reopen_session_ids(
                [deserialize_from_dynamodb_item(existing_item)] if existing_item else [], [serialized_session]
            )
            try:
                self.client.put_item(**put_kwargs)
            except self.client.exceptions.ConditionalCheckFailedException:
                return None
            if session.session_id in reopen_session_ids:
                # The stored created_at, which keeps the session on the day it was created
                self._reopen_metrics_days([serialized_session.get("created_at")])

            # Runs are persisted separately via upsert_run by the caller (agent loop).
            # Attach the in-memory runs to the returned dict so callers see them.
            serialized_session["runs"] = [r.to_dict() if hasattr(r, "to_dict") else r for r in (session.runs or [])]
            return deserialize_session_result(serialized_session, session, deserialize)

        except Exception as e:
            log_error(f"Failed to upsert session {session.session_id}: {str(e)}")
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
                f"DynamoDb doesn't support efficient bulk operations, falling back to individual upserts for {len(sessions)} sessions"
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

    # --- User Memory ---

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        """
        Delete a user memory from the database.

        Args:
            memory_id: The ID of the memory to delete.
            user_id: The ID of the user (optional, for filtering).

        Raises:
            Exception: If any error occurs while deleting the user memory.
        """
        try:
            # If user_id is provided, verify the memory belongs to the user before deleting
            if user_id is not None:
                response = self.client.get_item(
                    TableName=self.memory_table_name,
                    Key={"memory_id": {"S": memory_id}},
                )
                item = response.get("Item")
                if item:
                    memory_data = deserialize_from_dynamodb_item(item)
                    if memory_data.get("user_id") != user_id:
                        log_debug(f"Memory {memory_id} does not belong to user {user_id}")
                        return

            self.client.delete_item(
                TableName=self.memory_table_name,
                Key={"memory_id": {"S": memory_id}},
            )
            log_debug(f"Deleted user memory {memory_id}")

        except Exception as e:
            log_error(f"Failed to delete user memory {memory_id}: {str(e)}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """
        Delete user memories from the database in batches.

        Args:
            memory_ids: List of memory IDs to delete
            user_id: The ID of the user (optional, for filtering).

        Raises:
            Exception: If any error occurs while deleting the user memories.
        """

        try:
            # If user_id is provided, filter memory_ids to only those belonging to the user
            if user_id is not None:
                filtered_memory_ids = []
                for memory_id in memory_ids:
                    response = self.client.get_item(
                        TableName=self.memory_table_name,
                        Key={"memory_id": {"S": memory_id}},
                    )
                    item = response.get("Item")
                    if item:
                        memory_data = deserialize_from_dynamodb_item(item)
                        if memory_data.get("user_id") == user_id:
                            filtered_memory_ids.append(memory_id)
                memory_ids = filtered_memory_ids

            for i in range(0, len(memory_ids), DYNAMO_BATCH_SIZE_LIMIT):
                batch = memory_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]

                delete_requests = []
                for memory_id in batch:
                    delete_requests.append({"DeleteRequest": {"Key": {"memory_id": {"S": memory_id}}}})

                batch_write_with_retry(self.client, {self.memory_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete user memories: {str(e)}")
            raise e

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            List[str]: List of unique memory topics.
        """
        try:
            table_name = self._get_table("memories")
            if table_name is None:
                return []

            scan_kwargs: Dict[str, Any] = {"TableName": table_name}
            if user_id is not None:
                scan_kwargs["FilterExpression"] = "user_id = :user_id"
                scan_kwargs["ExpressionAttributeValues"] = {":user_id": {"S": user_id}}

            # Scan the table to get memories
            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Extract topics from all memories
            all_topics: set[str] = set()
            for item in items:
                memory_data = deserialize_from_dynamodb_item(item)
                topics = memory_data.get("topics") or []
                if isinstance(topics, list):
                    all_topics.update(topics)

            return list(all_topics)

        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            raise e

    def get_user_memory(
        self,
        memory_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """
        Get a user memory from the database as a UserMemory object.

        Args:
            memory_id: The ID of the memory to get.
            deserialize: Whether to deserialize the memory.
            user_id: The ID of the user (optional, for filtering).

        Returns:
            Optional[UserMemory]: The user memory data if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the user memory.
        """
        try:
            table_name = self._get_table("memories")
            response = self.client.get_item(TableName=table_name, Key={"memory_id": {"S": memory_id}})

            item = response.get("Item")
            if not item:
                return None

            item = deserialize_from_dynamodb_item(item)

            # Filter by user_id if provided
            if user_id and item.get("user_id") != user_id:
                return None

            if not deserialize:
                return item

            return UserMemory.from_dict(item)

        except Exception as e:
            log_error(f"Failed to get user memory {memory_id}: {str(e)}")
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
        """
        Get user memories from the database as a list of UserMemory objects.

        Args:
            user_id: The ID of the user to get the memories for.
            agent_id: The ID of the agent to get the memories for.
            team_id: The ID of the team to get the memories for.
            workflow_id: The ID of the workflow to get the memories for.
            topics: The topics to filter the memories by.
            search_content: The content to search for in the memories.
            limit: The maximum number of memories to return.
            page: The page number to return.
            sort_by: The field to sort the memories by.
            sort_order: The order to sort the memories by.
            deserialize: Whether to deserialize the memories.

        Returns:
            Union[List[UserMemory], List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]: The user memories data.

        Raises:
            Exception: If any error occurs while getting the user memories.
        """
        try:
            table_name = self._get_table("memories")
            if table_name is None:
                return [] if deserialize else ([], 0)

            # Build filter expressions for component filters
            (
                filter_expression,
                expression_attribute_names,
                expression_attribute_values,
            ) = build_query_filter_expression(filters={"agent_id": agent_id, "team_id": team_id})

            # Build topic filter expression if topics provided
            if topics:
                topic_filter, topic_values = build_topic_filter_expression(topics)
                expression_attribute_values.update(topic_values)
                filter_expression = f"{filter_expression} AND {topic_filter}" if filter_expression else topic_filter

            # Add search content filter if provided
            if search_content:
                search_filter = "contains(memory, :search_content)"
                expression_attribute_values[":search_content"] = {"S": search_content}
                filter_expression = f"{filter_expression} AND {search_filter}" if filter_expression else search_filter

            # Determine whether to use GSI query or table scan
            if user_id is not None:
                # Use GSI query when user_id is provided
                key_condition_expression = "#user_id = :user_id"

                # Set up expression attributes for GSI key condition
                expression_attribute_names["#user_id"] = "user_id"
                expression_attribute_values[":user_id"] = {"S": user_id}

                # Execute query with pagination
                items = execute_query_with_pagination(
                    self.client,
                    table_name,
                    "user_id-updated_at-index",
                    key_condition_expression,
                    expression_attribute_names,
                    expression_attribute_values,
                    filter_expression,
                    sort_by,
                    sort_order,
                    limit,
                    page,
                )
            else:
                # Use table scan when user_id is None
                scan_kwargs = {"TableName": table_name}

                if filter_expression:
                    scan_kwargs["FilterExpression"] = filter_expression
                if expression_attribute_names:
                    scan_kwargs["ExpressionAttributeNames"] = expression_attribute_names  # type: ignore
                if expression_attribute_values:
                    scan_kwargs["ExpressionAttributeValues"] = expression_attribute_values  # type: ignore

                # Execute scan
                response = self.client.scan(**scan_kwargs)
                items = response.get("Items", [])

                # Handle pagination for scan
                while "LastEvaluatedKey" in response:
                    scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.scan(**scan_kwargs)
                    items.extend(response.get("Items", []))

            items = [deserialize_from_dynamodb_item(item) for item in items]

            if sort_by and sort_by != "updated_at":
                items = apply_sorting(items, sort_by, sort_order)

            if page:
                paginated_items = apply_pagination(items, limit, page)

            if not deserialize:
                return paginated_items, len(items)

            return [UserMemory.from_dict(item) for item in items]

        except Exception as e:
            log_error(f"Failed to get user memories: {str(e)}")
            raise e

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memories stats.

        Args:
            limit (Optional[int]): The maximum number of user stats to return.
            page (Optional[int]): The page number.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Returns:
            Tuple[List[Dict[str, Any]], int]: A list of dictionaries containing user stats and total count.

        Example:
        (
            [
                {
                    "user_id": "123",
                    "total_memories": 10,
                    "last_memory_updated_at": 1714560000,
                },
            ],
            total_count: 1,
        )
        """
        try:
            table_name = self._get_table("memories")

            # Build filter expression for user_id if provided
            filter_expression = None
            expression_attribute_values = {}
            if user_id is not None:
                filter_expression = "user_id = :user_id"
                expression_attribute_values[":user_id"] = {"S": user_id}

            scan_kwargs = {"TableName": table_name}
            if filter_expression:
                scan_kwargs["FilterExpression"] = filter_expression
            if expression_attribute_values:
                scan_kwargs["ExpressionAttributeValues"] = expression_attribute_values  # type: ignore

            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Aggregate stats by user_id
            user_stats = {}
            for item in items:
                memory_data = deserialize_from_dynamodb_item(item)
                current_user_id = memory_data.get("user_id")

                if current_user_id:
                    if current_user_id not in user_stats:
                        user_stats[current_user_id] = {
                            "user_id": current_user_id,
                            "total_memories": 0,
                            "last_memory_updated_at": None,
                        }

                    user_stats[current_user_id]["total_memories"] += 1

                    updated_at = memory_data.get("updated_at")
                    if updated_at:
                        updated_at_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        updated_at_timestamp = int(updated_at_dt.timestamp())

                        if updated_at_timestamp and (
                            user_stats[current_user_id]["last_memory_updated_at"] is None
                            or updated_at_timestamp > user_stats[current_user_id]["last_memory_updated_at"]
                        ):
                            user_stats[current_user_id]["last_memory_updated_at"] = updated_at_timestamp

            # Convert to list and apply sorting
            stats_list = list(user_stats.values())
            stats_list.sort(
                key=lambda x: x["last_memory_updated_at"] if x["last_memory_updated_at"] is not None else 0,
                reverse=True,
            )

            total_count = len(stats_list)

            # Apply pagination
            if limit is not None:
                start_index = 0
                if page is not None and page > 1:
                    start_index = (page - 1) * limit
                stats_list = stats_list[start_index : start_index + limit]

            return stats_list, total_count

        except Exception as e:
            log_error(f"Failed to get user memory stats: {str(e)}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """
        Upsert a user memory into the database.

        Args:
            memory: The memory to upsert.

        Returns:
            Optional[Dict[str, Any]]: The upserted memory data if successful, None otherwise.
        """
        try:
            table_name = self._get_table("memories", create_table_if_not_found=True)
            memory_dict = memory.to_dict()
            memory_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            item = serialize_to_dynamo_item(memory_dict)

            self.client.put_item(TableName=table_name, Item=item)

            if not deserialize:
                return memory_dict

            return UserMemory.from_dict(memory_dict)

        except Exception as e:
            log_error(f"Failed to upsert user memory: {str(e)}")
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
                f"DynamoDb doesn't support efficient bulk operations, falling back to individual upserts for {len(memories)} memories"
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
            table_name = self._get_table("memories")

            # Scan the table to get all items
            response = self.client.scan(TableName=table_name)
            items = response.get("Items", [])

            # Handle pagination for scan
            while "LastEvaluatedKey" in response:
                response = self.client.scan(TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response.get("Items", []))

            if not items:
                return

            # Delete items in batches
            for i in range(0, len(items), DYNAMO_BATCH_SIZE_LIMIT):
                batch = items[i : i + DYNAMO_BATCH_SIZE_LIMIT]

                delete_requests = []
                for item in batch:
                    # Extract the memory_id from the item
                    memory_id = item.get("memory_id", {}).get("S")
                    if memory_id:
                        delete_requests.append({"DeleteRequest": {"Key": {"memory_id": {"S": memory_id}}}})

                if delete_requests:
                    batch_write_with_retry(self.client, {table_name: delete_requests})

        except Exception as e:
            from agno.utils.log import log_warning

            log_warning(f"Exception deleting all memories: {str(e)}")
            raise e

    # --- Metrics ---

    def _reopen_metrics_days(self, created_ats: Sequence[Optional[int]]) -> None:
        """Reopen the metrics of each day a write changed, right after the write, so the next calculation rebuilds
        it. A day it could not reopen is retried by the next write.

        Args:
            created_ats: The stored created_at of each run or session the write changed.
        """
        days = sorted(
            {day for created_at in created_ats if (day := metrics_day_to_reopen(created_at)) is not None}
            | self._metrics_days_not_reopened
        )
        if not days:
            return
        try:
            for day in days:
                reopen_metrics_day(self.client, self.aggregate_metrics_table_name, day)
            self._metrics_days_not_reopened.difference_update(days)
        except self.client.exceptions.ResourceNotFoundException:
            # No day was calculated yet, so there is nothing to reopen
            self._metrics_days_not_reopened.clear()
        except Exception as e:
            self._metrics_days_not_reopened.update(days)
            log_warning(
                f"Could not reopen the metrics of {', '.join(str(day) for day in days)}: {database_error_message(e)}"
            )

    def _get_metrics_refresh_row(self, refreshes_table_name: str) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get the item of the metrics refreshes table, and the locked_at at or before which its lock is stale, by the
        process clock."""
        stale_lock_threshold = int(time.time()) - METRICS_LOCK_SECONDS
        try:
            item = self.client.get_item(
                TableName=refreshes_table_name,
                Key={"id": {"S": METRICS_REFRESH_ID}},
                ConsistentRead=True,
            ).get("Item")
        except self.client.exceptions.ResourceNotFoundException:
            item = None
        if not item:
            # Before the first refresh there is no lock to judge stale
            return None, 0
        return deserialize_metrics_refresh_row(deserialize_from_dynamodb_item(item)), stale_lock_threshold

    def _claim_metrics_refresh(self, refreshes_table_name: str, worker_id: str) -> Optional[Dict[str, Any]]:
        """Claim the item of the metrics refreshes table, so one process calculates metrics at a time.

        Args:
            refreshes_table_name: The metrics refreshes table.
            worker_id: The id of this calculation, which heartbeats and releases the claim.

        Returns:
            Optional[Dict[str, Any]]: The claimed item, with when the last calculation finished and its fingerprint.
                None when another process holds it.
        """
        now = int(time.time())
        try:
            # One conditional write, so two processes never both find the item free
            response = self.client.update_item(
                TableName=refreshes_table_name,
                Key={"id": {"S": METRICS_REFRESH_ID}},
                UpdateExpression="SET #locked_by = :worker_id, #locked_at = :now, #started_at = :now, "
                "#status = :running REMOVE #error",
                # A stale lock is taken over: the process that held it stopped
                ConditionExpression="attribute_not_exists(#locked_by) OR #locked_at <= :stale_lock_threshold",
                ExpressionAttributeNames={
                    "#locked_by": "locked_by",
                    "#locked_at": "locked_at",
                    "#started_at": "started_at",
                    "#status": "status",
                    "#error": "error",
                },
                ExpressionAttributeValues={
                    ":worker_id": {"S": worker_id},
                    ":now": {"N": str(now)},
                    ":running": {"S": "running"},
                    ":stale_lock_threshold": {"N": str(now - METRICS_LOCK_SECONDS)},
                },
                ReturnValues="ALL_NEW",
            )
        except self.client.exceptions.ConditionalCheckFailedException:
            return None
        return deserialize_metrics_refresh_row(deserialize_from_dynamodb_item(response["Attributes"]))

    def _heartbeat_metrics_refresh(self, refreshes_table_name: str, worker_id: str) -> bool:
        """Refresh locked_at for this worker's metrics refresh. False when another process took it over."""
        try:
            self.client.update_item(**heartbeat_metrics_refresh_update(refreshes_table_name, worker_id))
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            return False

    def _release_metrics_refresh(
        self,
        refreshes_table_name: str,
        worker_id: Optional[str],
        error: Optional[str] = None,
        fingerprint: Optional[List[Any]] = None,
        stopped: bool = False,
        claimed_fingerprint: Optional[List[Any]] = None,
    ) -> None:
        """Release the item of the metrics refreshes table: completed, with the fingerprint, without an error, failed
        with one, and as the last completed refresh left it when the calculation stopped.

        Args:
            refreshes_table_name: The metrics refreshes table.
            worker_id: The id of the calculation that claimed the item. None writes the item only while no process
                holds it, and creates it before any refresh.
            error: The error the calculation failed with. None when it completed.
            fingerprint: The fingerprint of yesterday and today, stored once it completed.
            stopped: Whether the calculation stopped before it finished.
            claimed_fingerprint: The fingerprint of the claimed item. A rebuild that marked another one since keeps
                its mark.
        """
        names = {"#locked_by": "locked_by", "#locked_at": "locked_at", "#status": "status", "#error": "error"}
        values: Dict[str, Any] = {}
        if worker_id is None:
            lock_condition = "attribute_not_exists(#locked_by)"
        else:
            values[":worker_id"] = {"S": worker_id}
            lock_condition = "#locked_by = :worker_id"
        try:
            if stopped:
                # The days it did not reach stay open for the next calculation; a first one that stopped has none to
                # show
                names["#finished_at"] = "finished_at"
                try:
                    self.client.update_item(
                        TableName=refreshes_table_name,
                        Key={"id": {"S": METRICS_REFRESH_ID}},
                        UpdateExpression="SET #status = :completed REMOVE #locked_by, #locked_at, #error",
                        ConditionExpression=f"{lock_condition} AND attribute_exists(#finished_at)",
                        ExpressionAttributeNames=names,
                        ExpressionAttributeValues={**values, ":completed": {"S": "completed"}},
                    )
                    return
                except self.client.exceptions.ConditionalCheckFailedException:
                    names.pop("#finished_at")
                    error = METRICS_STOPPED_ERROR
            if error is None:
                names.update({"#finished_at": "finished_at", "#fingerprint": "fingerprint"})
                values.update({":completed": {"S": "completed"}, ":finished_at": {"N": str(int(time.time()))}})
                update_expression = "SET #status = :completed, #finished_at = :finished_at"
                remove_parts = ["#locked_by", "#locked_at", "#error"]
                # A fingerprint of nothing is no attribute, as a NULL column
                if fingerprint is None:
                    remove_parts.append("#fingerprint")
                else:
                    update_expression += ", #fingerprint = :fingerprint"
                    values[":fingerprint"] = {"S": json.dumps(fingerprint)}
                update_expression += " REMOVE " + ", ".join(remove_parts)
                # A rebuild that marked the fingerprint after the claim keeps its mark, so the next calculation rebuilds
                # yesterday and today. No fingerprint is no attribute, which a claim of None compares equal to
                fingerprint_condition = "attribute_not_exists(#fingerprint)"
                claimed_values: Dict[str, Any] = {}
                if claimed_fingerprint is not None:
                    fingerprint_condition = "#fingerprint = :claimed_fingerprint"
                    claimed_values[":claimed_fingerprint"] = {"S": json.dumps(claimed_fingerprint)}
                try:
                    self.client.update_item(
                        TableName=refreshes_table_name,
                        Key={"id": {"S": METRICS_REFRESH_ID}},
                        UpdateExpression=update_expression,
                        ConditionExpression=f"{lock_condition} AND {fingerprint_condition}",
                        ExpressionAttributeNames=names,
                        ExpressionAttributeValues={**values, **claimed_values},
                    )
                    return
                except self.client.exceptions.ConditionalCheckFailedException:
                    names.pop("#fingerprint")
                    values.pop(":fingerprint", None)
                    update_expression = (
                        "SET #status = :completed, #finished_at = :finished_at REMOVE #locked_by, #locked_at, #error"
                    )
            else:
                values.update({":failed": {"S": "failed"}, ":error": {"S": error}})
                update_expression = "SET #status = :failed, #error = :error REMOVE #locked_by, #locked_at"
                if worker_id is None:
                    # Before any refresh there is no item to update, and the update creates it
                    names["#started_at"] = "started_at"
                    values[":now"] = {"N": str(int(time.time()))}
                    update_expression = (
                        "SET #status = :failed, #error = :error, #started_at = if_not_exists(#started_at, :now) "
                        "REMOVE #locked_by, #locked_at"
                    )
            try:
                self.client.update_item(
                    TableName=refreshes_table_name,
                    Key={"id": {"S": METRICS_REFRESH_ID}},
                    UpdateExpression=update_expression,
                    ConditionExpression=lock_condition,
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                )
            except self.client.exceptions.ConditionalCheckFailedException:
                # Another process took the refresh over after this one's lock went stale
                pass
        except Exception as e:
            log_debug(f"Error releasing metrics refresh: {e}")

    def _query_metrics_sources(
        self,
        table_name: str,
        index_name: str,
        key_name: str,
        key_values: List[str],
        attributes: List[str],
        start_timestamp: int,
        end_timestamp: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get the sessions or runs created in the given time range, with only the given attributes.

        Args:
            table_name: The sessions or runs table.
            index_name: The index keyed by key_name and created_at.
            key_name: The hash key of the index.
            key_values: Every value of the hash key to read.
            attributes: The attributes to read.
            start_timestamp: The start of the range, included.
            end_timestamp: The end of the range, not included. ``None`` reads every later record.

        Returns:
            List[Dict[str, Any]]: The records.
        """
        names = {f"#{name}": name for name in [key_name, "created_at"] + attributes}
        key_condition = f"#{key_name} = :key AND #created_at >= :start_ts"
        values: Dict[str, Any] = {":start_ts": {"N": str(start_timestamp)}}
        if end_timestamp is not None:
            key_condition = f"#{key_name} = :key AND #created_at BETWEEN :start_ts AND :end_ts"
            # BETWEEN includes its end, and the range does not
            values[":end_ts"] = {"N": str(end_timestamp - 1)}

        records: List[Dict[str, Any]] = []
        for key_value in key_values:
            items = query_all_items(
                self.client,
                {
                    "TableName": table_name,
                    "IndexName": index_name,
                    "KeyConditionExpression": key_condition,
                    "ExpressionAttributeNames": names,
                    "ExpressionAttributeValues": {**values, ":key": {"S": key_value}},
                    "ProjectionExpression": ", ".join(f"#{name}" for name in attributes),
                },
            )
            records.extend(deserialize_from_dynamodb_item(item) for item in items)
        return records

    def _get_metrics_legacy_sessions(
        self, table_name: str, start_timestamp: int, end_timestamp: int
    ) -> List[Dict[str, Any]]:
        """Get the sessions that keep runs in the legacy runs field and may hold a run of the given time range.

        A session holds runs created after it started and before it was last written.

        Args:
            table_name: The sessions table.
            start_timestamp: The start of the range, included.
            end_timestamp: The end of the range, not included.

        Returns:
            List[Dict[str, Any]]: The sessions, with their id, user, creation time and legacy runs.
        """
        sessions: List[Dict[str, Any]] = []
        for session_type in METRICS_COMPONENT_TYPES:
            items = query_all_items(
                self.client,
                {
                    "TableName": table_name,
                    "IndexName": "session_type-created_at-index",
                    "KeyConditionExpression": "#session_type = :session_type AND #created_at < :end_ts",
                    "FilterExpression": "attribute_exists(#runs) AND "
                    "(#updated_at >= :start_ts OR attribute_not_exists(#updated_at))",
                    "ExpressionAttributeNames": {
                        "#session_type": "session_type",
                        "#created_at": "created_at",
                        "#updated_at": "updated_at",
                        "#session_id": "session_id",
                        "#user_id": "user_id",
                        "#runs": "runs",
                    },
                    "ExpressionAttributeValues": {
                        ":session_type": {"S": session_type},
                        ":start_ts": {"N": str(start_timestamp)},
                        ":end_ts": {"N": str(end_timestamp)},
                    },
                    "ProjectionExpression": "#session_id, #user_id, #created_at, #updated_at, #runs",
                },
            )
            sessions.extend(deserialize_from_dynamodb_item(item) for item in items)
        return [
            session
            for session in sessions
            if (session.get("updated_at") or session.get("created_at") or 0) >= start_timestamp
        ]

    def _get_aggregate_metrics_items(
        self,
        aggregate_metrics_table_name: str,
        aggregation_period: str,
        user_id: Optional[str],
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
        completed: Optional[bool] = None,
        attributes: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get the aggregate metrics rows of one period in the given date range, oldest first.

        Args:
            aggregate_metrics_table_name: The aggregate metrics table.
            aggregation_period: "daily" or "monthly".
            user_id: The rows of this user, ``""`` the everyone rows, ``None`` the rows of every user and the everyone
                rows, which are read from the period's index a moment after a write.
            starting_date: The first day to read. ``None`` reads from the first one.
            ending_date: The last day to read. ``None`` reads to the last one.
            completed: Only the rows completed, or only the everyone rows not completed, which are read from the index
                of the open rows a moment after a write. ``None`` reads both.
            attributes: Only these attributes of each row. ``None`` reads every one.

        Returns:
            List[Dict[str, Any]]: The rows.
        """
        names = {"#key": "aggregation_period" if user_id is None else "period_user_id", "#date": "date"}
        values: Dict[str, Any] = {
            ":key": {
                "S": aggregation_period
                if user_id is None
                else aggregate_metrics_period_user_id(aggregation_period, user_id)
            }
        }
        key_condition = "#key = :key AND #date BETWEEN :start_date AND :end_date"
        values[":start_date"] = {"S": (starting_date or date.min).isoformat()}
        values[":end_date"] = {"S": (ending_date or date.max).isoformat()}
        query_kwargs: Dict[str, Any] = {
            "TableName": aggregate_metrics_table_name,
            "KeyConditionExpression": key_condition,
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
        if completed is False:
            # Only an open everyone row has open_period, so finding the open rows never reads a completed one
            names["#key"] = "open_period"
            values[":key"] = {"S": aggregation_period}
            query_kwargs["IndexName"] = "open_period-date-index"
        elif user_id is None:
            query_kwargs["IndexName"] = "aggregation_period-date-index"
        else:
            query_kwargs["ConsistentRead"] = True
        if completed:
            query_kwargs["FilterExpression"] = "#completed = :completed"
            names["#completed"] = "completed"
            values[":completed"] = {"BOOL": completed}
        if attributes is not None:
            names.update({f"#{name}": name for name in attributes})
            query_kwargs["ProjectionExpression"] = ", ".join(f"#{name}" for name in attributes)
        return [deserialize_metrics_row(item) for item in query_all_items(self.client, query_kwargs)]

    def _get_component_metrics_rows(
        self, table_name: str, day: date, user_id: Optional[str] = None, attributes: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get the component metrics rows of one day: of every user, or of no user for ``""``, with only the given
        attributes of each when there are any."""
        query_kwargs: Dict[str, Any] = {
            "TableName": table_name,
            "KeyConditionExpression": "#date = :date",
            "ExpressionAttributeNames": {"#date": "date"},
            "ExpressionAttributeValues": {":date": {"S": day.isoformat()}},
            "ConsistentRead": True,
        }
        if user_id == "":
            query_kwargs["FilterExpression"] = "#user_id = :user_id"
            query_kwargs["ExpressionAttributeNames"]["#user_id"] = "user_id"
            query_kwargs["ExpressionAttributeValues"][":user_id"] = {"S": ""}
        if attributes is not None:
            query_kwargs["ExpressionAttributeNames"].update({f"#{name}": name for name in attributes})
            query_kwargs["ProjectionExpression"] = ", ".join(f"#{name}" for name in attributes)
        return [deserialize_metrics_row(item) for item in query_all_items(self.client, query_kwargs)]

    def _get_metrics_fingerprint(
        self, sessions_table_name: str, runs_table_name: str, yesterday: date
    ) -> Optional[List[Any]]:
        """Get the count and update times of the sessions and runs of yesterday and today. None while one of them was
        updated in the current second, which a second update in that same second would leave unchanged.

        DynamoDB has no SUM, so the update time of every session and run of the two days is read, through the indexes
        the calculation reads them with. A read is charged for the whole record, not only its update time."""
        start_timestamp = int(datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        sessions = self._query_metrics_sources(
            sessions_table_name,
            "session_type-created_at-index",
            "session_type",
            list(METRICS_COMPONENT_TYPES),
            ["created_at", "updated_at"],
            start_timestamp,
        )
        runs = self._query_metrics_sources(
            runs_table_name,
            "status-created_at-index",
            "status",
            [status.value for status in RunStatus],
            ["created_at", "updated_at"],
            start_timestamp,
        )
        return get_metrics_fingerprint(sessions, runs, yesterday)

    def _get_metrics_data_days(
        self,
        table_name: str,
        index_name: str,
        key_name: str,
        key_values: List[str],
        today: date,
        starting_date: Optional[date] = None,
    ) -> Set[date]:
        """Get every day up to today, from starting_date on, with a session or run, through the index keyed by
        key_name and created_at.

        Each day found is one query for the first record after it, so a first calculation never reads every record.
        """
        days: Set[date] = set()
        for key_value in key_values:
            start_timestamp = (
                int(datetime.combine(starting_date, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
                if starting_date is not None
                else 0
            )
            while True:
                items = self.client.query(
                    TableName=table_name,
                    IndexName=index_name,
                    KeyConditionExpression="#key = :key AND #created_at >= :start_ts",
                    ExpressionAttributeNames={"#key": key_name, "#created_at": "created_at"},
                    ExpressionAttributeValues={":key": {"S": key_value}, ":start_ts": {"N": str(start_timestamp)}},
                    ProjectionExpression="#created_at",
                    Limit=1,
                ).get("Items", [])
                if not items:
                    break
                day = datetime.fromtimestamp(
                    deserialize_from_dynamodb_item(items[0])["created_at"], tz=timezone.utc
                ).date()
                if day > today:
                    break
                days.add(day)
                start_timestamp = int(
                    datetime.combine(day + timedelta(days=1), datetime.min.time())
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
        return days

    def _get_metrics_dates_to_calculate(
        self,
        aggregate_metrics_table_name: str,
        sessions_table_name: str,
        runs_table_name: str,
        refresh_row: Dict[str, Any],
        rebuild_from: Optional[date] = None,
    ) -> Tuple[List[date], Optional[List[Any]]]:
        """Get the days whose metrics a calculation rebuilds, and the fingerprint of yesterday and today.

        Args:
            aggregate_metrics_table_name: The aggregate metrics table.
            sessions_table_name: The sessions table.
            runs_table_name: The runs table.
            refresh_row: The item of the metrics refreshes table, from _claim_metrics_refresh.
            rebuild_from: The first day of a rebuild.

        Returns:
            Tuple[List[date], Optional[List[Any]]]: The days, oldest first, and the fingerprint to keep on the item of
                the metrics refreshes table.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        dates_to_process: Set[date] = set()
        fingerprint = self._get_metrics_fingerprint(sessions_table_name, runs_table_name, yesterday)
        first_calculation = refresh_row["finished_at"] is None
        # Yesterday and today, when their sessions or runs changed since the last calculation
        if first_calculation or fingerprint is None or fingerprint != refresh_row["fingerprint"]:
            dates_to_process.update([yesterday, today])

        # Every earlier day still open: not yet completed, or reopened by a write since
        dates_to_process.update(
            row["date"]
            for row in self._get_aggregate_metrics_items(
                aggregate_metrics_table_name,
                "daily",
                "",
                ending_date=yesterday - timedelta(days=1),
                completed=False,
                attributes=["date"],
            )
        )
        # Every earlier day from the day before the last calculation finished, whose writes reopened nothing while
        # it was yesterday or today
        if not first_calculation:
            dates_to_process.update(metrics_days_since_last_calculation(refresh_row["finished_at"], yesterday))

        # Until a first calculation has finished, every day with a session or a run not yet completed; with
        # rebuild_from, every day with one from that date on
        if first_calculation or rebuild_from is not None:
            completed_days: Set[date] = set()
            if first_calculation:
                completed_days = {
                    row["date"]
                    for row in self._get_aggregate_metrics_items(
                        aggregate_metrics_table_name, "daily", "", completed=True, attributes=["date"]
                    )
                }
            # Only days with data, so one session dated long ago never builds every empty day since
            starting_date = rebuild_from if not first_calculation else None
            data_days = self._get_metrics_data_days(
                sessions_table_name,
                "session_type-created_at-index",
                "session_type",
                list(METRICS_COMPONENT_TYPES),
                today,
                starting_date,
            ) | self._get_metrics_data_days(
                runs_table_name,
                "status-created_at-index",
                "status",
                [status.value for status in RunStatus],
                today,
                starting_date,
            )
            for data_date in data_days:
                # A rebuild takes every day with data from its first day, completed or not
                rebuilt = rebuild_from is not None and data_date >= rebuild_from
                if rebuilt or (first_calculation and data_date not in completed_days):
                    dates_to_process.add(data_date)

        return sorted(dates_to_process), fingerprint

    def _get_open_metrics_months(self, aggregate_metrics_table_name: str) -> List[date]:
        """Get the first day of every month before the current one whose month row is still open: not completed yet,
        or reopened by a day a calculation rebuilt before it stopped."""
        current_month = datetime.now(timezone.utc).date().replace(day=1)
        return [
            row["date"]
            for row in self._get_aggregate_metrics_items(
                aggregate_metrics_table_name,
                "monthly",
                "",
                ending_date=current_month - timedelta(days=1),
                completed=False,
                attributes=["date"],
            )
        ]

    def _get_metrics_runs(
        self, runs_table_name: str, run_ids: List[str], attributes: List[str]
    ) -> List[Dict[str, Any]]:
        """Get the stored runs of the given ids, with only the given attributes."""
        runs: List[Dict[str, Any]] = []
        for i in range(0, len(run_ids), DYNAMO_BATCH_GET_SIZE_LIMIT):
            batch = run_ids[i : i + DYNAMO_BATCH_GET_SIZE_LIMIT]
            request_items: Dict[str, Any] = {
                runs_table_name: {
                    "Keys": [{"run_id": {"S": run_id}} for run_id in batch],
                    "ExpressionAttributeNames": {f"#{name}": name for name in attributes},
                    "ProjectionExpression": ", ".join(f"#{name}" for name in attributes),
                }
            }
            runs.extend(
                deserialize_from_dynamodb_item(item)
                for item in batch_get_with_retry(self.client, request_items).get(runs_table_name, [])
            )
        return runs

    def _get_metrics_legacy_runs(
        self,
        sessions_table_name: str,
        runs_table_name: str,
        start_timestamp: int,
        end_timestamp: int,
    ) -> Tuple[Dict[date, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
        """Get the runs not yet migrated out of the sessions' legacy runs field, created in the given time range.

        Args:
            sessions_table_name: The sessions table.
            runs_table_name: The runs table. A run it also holds is read from there.
            start_timestamp: The start of the range, included.
            end_timestamp: The end of the range, not included.

        Returns:
            Tuple[Dict[date, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]: The legacy runs by the UTC day they
                were created on, and by their id.
        """
        legacy_runs = [
            legacy_run
            for legacy_run in get_metrics_legacy_runs(
                self._get_metrics_legacy_sessions(sessions_table_name, start_timestamp, end_timestamp)
            )
            if start_timestamp <= (legacy_run["created_at"] or 0) < end_timestamp
        ]
        # The runs table wins on a run in both, as merge_runs_table_with_legacy_blob does
        migrated_run_ids = {
            run["run_id"]
            for run in self._get_metrics_runs(
                runs_table_name, [legacy_run["run_id"] for legacy_run in legacy_runs], ["run_id"]
            )
        }
        legacy_runs_by_day: Dict[date, List[Dict[str, Any]]] = {}
        legacy_runs_by_id: Dict[str, Dict[str, Any]] = {}
        for legacy_run in legacy_runs:
            if legacy_run["run_id"] in migrated_run_ids:
                continue
            legacy_run_day = datetime.fromtimestamp(legacy_run["created_at"], tz=timezone.utc).date()
            legacy_runs_by_day.setdefault(legacy_run_day, []).append(legacy_run)
            legacy_runs_by_id[legacy_run["run_id"]] = legacy_run
        return legacy_runs_by_day, legacy_runs_by_id

    def _get_metrics_parent_runs(self, runs_table_name: str, parent_run_ids: List[str]) -> List[Dict[str, Any]]:
        """Get the stored runs that started the given runs, and the runs that started those, up to the whole run."""
        parent_runs: List[Dict[str, Any]] = []
        seen_run_ids: Set[str] = set()
        while parent_run_ids:
            seen_run_ids.update(parent_run_ids)
            parent_runs.extend(
                self._get_metrics_runs(
                    runs_table_name,
                    parent_run_ids,
                    ["run_id", "run_type", "agent_id", "team_id", "workflow_id", "parent_run_id"],
                )
            )
            parent_run_ids = sorted(
                {run["parent_run_id"] for run in parent_runs if run.get("parent_run_id")} - seen_run_ids
            )
        return parent_runs

    def _write_aggregate_metrics_rows(
        self,
        aggregate_metrics_table_name: str,
        aggregate_metrics_rows: List[Dict[str, Any]],
        rows_changed: bool,
        read_version: Optional[int],
        refreshes_table_name: str,
        worker_id: str,
        row_writes: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> bool:
        """Write a period's rows: the given component metrics writes, then the user rows of the aggregate metrics table,
        then the everyone row, from build_aggregate_metrics_rows. False when another process took the refresh over.

        DynamoDB writes 25 items at most at once, so the everyone row is written last, conditional on the version it
        is completed by: it is completed only while it still has the version read before the period's rows.

        Args:
            aggregate_metrics_table_name: The aggregate metrics table.
            aggregate_metrics_rows: The period's rows, the everyone row first.
            rows_changed: Whether a component metrics row of the period was written or deleted.
            read_version: The version of the everyone row read before the period's rows were rebuilt.
            refreshes_table_name: The metrics refreshes table.
            worker_id: The id of this calculation, which holds the refresh.
            row_writes: The batch_write_item requests of the component metrics rows to write first, by table.
        """
        period, period_date = aggregate_metrics_rows[0]["aggregation_period"], aggregate_metrics_rows[0]["date"]
        # Read through the period's index, a moment behind a write: every row it compares was written by an earlier
        # calculation, as one calculation writes a period once
        stored_rows = self._get_aggregate_metrics_items(
            aggregate_metrics_table_name, period, None, period_date, period_date
        )
        stored_by_user = {row["user_id"]: row for row in stored_rows}
        everyone_row, changed_rows, stale_user_ids = aggregate_metrics_rows_to_write(
            aggregate_metrics_rows, stored_rows, rows_changed
        )
        writes = {table_name: list(requests) for table_name, requests in (row_writes or {}).items()}
        writes.setdefault(aggregate_metrics_table_name, []).extend(
            [
                {"DeleteRequest": {"Key": aggregate_metrics_key(period, period_date, user_id)}}
                for user_id in stale_user_ids
            ]
            + [
                {
                    "PutRequest": {
                        "Item": serialize_aggregate_metrics_row(
                            aggregate_metrics_row_to_store(row, stored_by_user.get(row["user_id"]), None)
                        )
                    }
                }
                for row in changed_rows
            ]
        )

        everyone_key = aggregate_metrics_key(period, period_date, "")
        expected_version = read_version
        # Heartbeated before the period's writes, so a process whose lock went stale writes none of them; a lock lost
        # between the batch requests reopens the period below
        if not self._heartbeat_metrics_refresh(refreshes_table_name, worker_id):
            return False
        # Rows of more than one request move the everyone row's version first, so a request that fails later never
        # leaves them under the version read before them; rows of one request keep it until the everyone row's write
        requests_count = sum(-(-len(requests) // DYNAMO_BATCH_SIZE_LIMIT) for requests in writes.values())
        if requests_count > 1 and "" in stored_by_user:
            self.client.update_item(
                TableName=aggregate_metrics_table_name,
                Key=everyone_key,
                UpdateExpression="ADD #version :one",
                ExpressionAttributeNames={"#version": "version"},
                ExpressionAttributeValues={":one": {"N": "1"}},
            )
            expected_version = read_version + 1 if read_version is not None else None
        for table_name, requests in writes.items():
            for i in range(0, len(requests), DYNAMO_BATCH_SIZE_LIMIT):
                batch_write_with_retry(self.client, {table_name: requests[i : i + DYNAMO_BATCH_SIZE_LIMIT]})

        if everyone_row is None:
            if not self._heartbeat_metrics_refresh(refreshes_table_name, worker_id):
                # The rows took several batch requests: a lock lost between them would leave stale rows completed
                reopen_metrics_row(self.client, aggregate_metrics_table_name, period_date, period)
                return False
            return True
        # Written last, and completed only while its version is still the one the rows were written under. A reopen
        # written between its read and its write fails the condition, and the row is read again, as
        # batch_write_with_retry retries
        for attempt in range(METRICS_WRITE_RETRIES + 1):
            stored_item = self.client.get_item(
                TableName=aggregate_metrics_table_name, Key=everyone_key, ConsistentRead=True
            ).get("Item")
            stored_row = deserialize_metrics_row(stored_item) if stored_item else None
            put_kwargs: Dict[str, Any] = {
                "TableName": aggregate_metrics_table_name,
                "Item": serialize_aggregate_metrics_row(
                    aggregate_metrics_row_to_store(everyone_row, stored_row, expected_version)
                ),
            }
            # Conditional on the version it is completed by, so a reopen written since keeps the period open
            if stored_row is None:
                put_kwargs["ConditionExpression"] = "attribute_not_exists(period_user_id)"
            else:
                put_kwargs["ConditionExpression"] = "#version = :version"
                put_kwargs["ExpressionAttributeNames"] = {"#version": "version"}
                put_kwargs["ExpressionAttributeValues"] = {":version": {"N": str(stored_row["version"])}}
            # Written with the heartbeat, so it is never written after another process took the refresh over
            try:
                self.client.transact_write_items(
                    TransactItems=[
                        {"Update": heartbeat_metrics_refresh_update(refreshes_table_name, worker_id)},
                        {"Put": put_kwargs},
                    ]
                )
                break
            except self.client.exceptions.TransactionCanceledException as e:
                reasons = e.response.get("CancellationReasons") or []
                if reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
                    # The rows took several batch requests: a lock lost between them would leave stale rows completed
                    reopen_metrics_row(self.client, aggregate_metrics_table_name, period_date, period)
                    return False
                if attempt == METRICS_WRITE_RETRIES:
                    raise
        return True

    def _calculate_date_metrics(
        self,
        table_name: str,
        aggregate_metrics_table_name: str,
        sessions_table_name: str,
        runs_table_name: str,
        date_to_process: date,
        legacy_runs: List[Dict[str, Any]],
        legacy_runs_by_id: Dict[str, Dict[str, Any]],
        refreshes_table_name: str,
        worker_id: str,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Rebuild one day's component and aggregate metrics rows. False when the refresh was taken over or stopped."""
        start_timestamp = int(
            datetime.combine(date_to_process, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
        )
        end_timestamp = int(
            datetime.combine(date_to_process + timedelta(days=1), datetime.min.time())
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        # Read before the day's runs, so a run written while they are read moves it
        everyone_item = self.client.get_item(
            TableName=aggregate_metrics_table_name,
            Key=aggregate_metrics_key("daily", date_to_process, ""),
            ProjectionExpression="#version",
            ExpressionAttributeNames={"#version": "version"},
            ConsistentRead=True,
        ).get("Item")
        read_version = deserialize_from_dynamodb_item(everyone_item).get("version") if everyone_item else None

        # The day's sessions and runs are read through the indexes keyed by their type and status and created_at,
        # one query per type and status
        sessions = self._query_metrics_sources(
            sessions_table_name,
            "session_type-created_at-index",
            "session_type",
            list(METRICS_COMPONENT_TYPES),
            ["session_id", "session_type", "user_id", "agent_id", "team_id", "workflow_id", "metadata", "session_data"],
            start_timestamp,
            end_timestamp,
        )
        # A manual compaction's usage, which no run carries, is read from the session's data
        sessions = [
            {**session, "compaction_metrics": (session.get("session_data") or {}).get("compaction_metrics")}
            for session in sessions
        ]
        runs = self._query_metrics_sources(
            runs_table_name,
            "status-created_at-index",
            "status",
            [status.value for status in RunStatus],
            [
                "run_id",
                "session_id",
                "run_type",
                "agent_id",
                "team_id",
                "workflow_id",
                "user_id",
                "parent_run_id",
                "status",
                "run_data",
            ],
            start_timestamp,
            end_timestamp,
        )
        # Checked once the runs are read too, so a stop never waits for the rest of a large day
        if should_stop is not None and should_stop():
            return False

        # A legacy run migrated to the runs table since the legacy runs were read is among the day's runs, and is
        # counted from there
        day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
        runs.extend(run for run in legacy_runs if run["run_id"] not in day_run_ids)

        # A nested run also stored as a run of its own is counted from that row, whatever day it is on
        run_ids = sorted(metrics_nested_run_ids(runs))
        stored_run_ids: Set[str] = {
            run["run_id"] for run in self._get_metrics_runs(runs_table_name, run_ids, ["run_id"])
        }
        # A nested run also stored in a legacy runs field of the rebuild, as a team stored its members' runs, is
        # counted from that run
        stored_run_ids.update(run_id for run_id in run_ids if run_id in legacy_runs_by_id)

        # A run started by a run of another day, such as a member run after midnight, names that run's agent, team or
        # workflow as its parent, read from the legacy runs of the rebuild or the runs table
        day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
        parent_run_ids = sorted({run["parent_run_id"] for run in runs if run.get("parent_run_id")} - day_run_ids)
        parent_runs = [legacy_runs_by_id[run_id] for run_id in parent_run_ids if run_id in legacy_runs_by_id]
        parent_run_ids = [run_id for run_id in parent_run_ids if run_id not in legacy_runs_by_id]

        # A remote member's run after midnight is named by its team's run of the day before
        team_runs = self._query_metrics_sources(
            runs_table_name,
            "session_id-created_at-index",
            "session_id",
            sorted(metrics_remote_member_team_session_ids(runs)),
            ["run_id", "session_id", "run_type", "agent_id", "team_id", "workflow_id", "parent_run_id", "run_data"],
            start_timestamp - 86400,
            start_timestamp,
        )
        parent_runs.extend(team_runs)
        parent_run_ids.extend(run["parent_run_id"] for run in team_runs if run.get("parent_run_id"))

        parent_runs.extend(self._get_metrics_parent_runs(runs_table_name, parent_run_ids))

        records = calculate_date_component_metrics(date_to_process, sessions, runs, stored_run_ids, parent_runs)
        stored_rows = self._get_component_metrics_rows(table_name, date_to_process)

        changed_rows, stale_keys = component_metrics_rows_to_write(records, stored_rows)
        requests: List[Dict[str, Any]] = []
        for user_id, component_type, component_id, parent_component_id, root_component_id in stale_keys:
            row_id = component_metrics_record_id(
                {
                    "user_id": user_id,
                    "component_type": component_type,
                    "component_id": component_id,
                    "parent_component_id": parent_component_id,
                    "root_component_id": root_component_id,
                }
            )
            requests.append(
                {"DeleteRequest": {"Key": {"date": {"S": date_to_process.isoformat()}, "id": {"S": row_id}}}}
            )
        # A stored row keeps its created_at, as an upsert does
        created_at_by_id = {row["id"]: row["created_at"] for row in stored_rows}
        for row in changed_rows:
            created_at = created_at_by_id.get(component_metrics_record_id(row), row["created_at"])
            requests.append(
                {"PutRequest": {"Item": serialize_component_metrics_row({**row, "created_at": created_at})}}
            )

        if not self._write_aggregate_metrics_rows(
            aggregate_metrics_table_name,
            build_aggregate_metrics_rows(records, "daily", date_to_process, metrics_day_completed(date_to_process)),
            rows_changed=bool(changed_rows or stale_keys),
            read_version=read_version,
            refreshes_table_name=refreshes_table_name,
            worker_id=worker_id,
            row_writes={table_name: requests},
        ):
            return False
        if changed_rows or stale_keys:
            # Reopened with the day, so a calculation that stops before its months leaves the month for the next
            reopen_metrics_month(self.client, aggregate_metrics_table_name, date_to_process.replace(day=1))
        return True

    def _calculate_month_metrics(
        self,
        table_name: str,
        aggregate_metrics_table_name: str,
        month_start: date,
        refreshes_table_name: str,
        worker_id: str,
    ) -> bool:
        """Rebuild the month rows of the aggregate metrics table from the component metrics rows of the month's days.
        False when another process took the refresh over."""
        everyone_item = self.client.get_item(
            TableName=aggregate_metrics_table_name,
            Key=aggregate_metrics_key("monthly", month_start, ""),
            ProjectionExpression="#version",
            ExpressionAttributeNames={"#version": "version"},
            ConsistentRead=True,
        ).get("Item")
        read_version = deserialize_from_dynamodb_item(everyone_item).get("version") if everyone_item else None

        # Day by day, so a month of many rows is added up a day at a time instead of held whole
        per_owner: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
        day = month_start
        while day <= metrics_month_end(month_start):
            add_metrics_month_totals(per_owner, self._get_component_metrics_rows(table_name, day))
            day += timedelta(days=1)

        # Added up per owner and component over the month, so a user of several days is one user of the month
        return self._write_aggregate_metrics_rows(
            aggregate_metrics_table_name,
            build_aggregate_metrics_month_rows(month_start, per_owner),
            rows_changed=False,
            read_version=read_version,
            refreshes_table_name=refreshes_table_name,
            worker_id=worker_id,
        )

    def calculate_metrics(self, rebuild_from: Optional[date] = None) -> Optional[list[dict]]:
        """Calculate metrics for every day that changed since the last calculation.

        One process calculates at a time, whichever process or replica it runs in: the others return at once,
        having read nothing.

        Args:
            rebuild_from: Also rebuild every day from this date to today, as after a release that changed how metrics
                are counted.

        Returns:
            Optional[list[dict]]: The metrics of the days calculated, or of today when nothing changed, as get_metrics
                returns them. None when another process is calculating them.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        try:
            calculated_dates = self.calculate_metrics_dates(rebuild_from=rebuild_from)
            if calculated_dates is None:
                return None
            if not calculated_dates:
                # A refresh that changed no day answers with today's metrics
                calculated_dates = [datetime.now(timezone.utc).date()]
            metrics, _ = self._get_metrics_rows(calculated_dates[0], calculated_dates[-1], None)
            return [metric for metric in metrics if metric["date"] in calculated_dates]

        except Exception as e:
            log_error(f"Failed to calculate metrics: {str(e)}")
            raise e

    def calculate_metrics_dates(
        self, should_stop: Optional[Callable[[], bool]] = None, rebuild_from: Optional[date] = None
    ) -> Optional[List[date]]:
        """Calculate metrics for every day that changed since the last calculation, as calculate_metrics does,
        without reading back the metrics of those days.

        Args:
            should_stop: Checked before each day and month, and once a day's runs are read. Once it returns True, the
                calculation releases the refresh and stops; the next one continues from the first day still open.
            rebuild_from: Also rebuild every day from this date to today.

        Returns:
            Optional[List[date]]: The days calculated, oldest first. None when another process is calculating them.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        table_name = self._get_table("component_metrics", create_table_if_not_found=True)
        aggregate_metrics_table_name = self._get_table("aggregate_metrics", create_table_if_not_found=True)
        refreshes_table_name = self._get_table("metrics_refreshes", create_table_if_not_found=True)
        sessions_table_name = self.session_table_name
        if (
            table_name is None
            or aggregate_metrics_table_name is None
            or refreshes_table_name is None
            or not self.table_exists(sessions_table_name)
        ):
            log_info("No session data found. Won't calculate metrics.")
            return []
        runs_table_name = self._get_table("runs", create_table_if_not_found=True)
        if runs_table_name is None:
            return []

        if rebuild_from is not None:
            # Reopened as a write reopens a day, before the claim, so a calculation another process is running
            # leaves them to the next one
            try:
                reopen_metrics_days_from(self.client, aggregate_metrics_table_name, rebuild_from)
                # Yesterday and today are picked by the fingerprint, so it is marked for the next one too
                try:
                    self.client.update_item(
                        TableName=refreshes_table_name,
                        Key={"id": {"S": METRICS_REFRESH_ID}},
                        UpdateExpression="SET #fingerprint = :rebuild",
                        # Before any refresh there is no item to mark, and an update would create one
                        ConditionExpression="attribute_exists(#id)",
                        ExpressionAttributeNames={"#id": "id", "#fingerprint": "fingerprint"},
                        ExpressionAttributeValues={":rebuild": {"S": json.dumps(["rebuild", uuid4().hex])}},
                    )
                except self.client.exceptions.ConditionalCheckFailedException:
                    pass
            except Exception as e:
                # Failed before the claim, so the refresh status shows it
                self._release_metrics_refresh(
                    refreshes_table_name,
                    None,
                    error=database_error_message(e),
                )
                raise

        worker_id = str(uuid4())
        # Claimed before anything is read, so a process that finds another calculating reads nothing
        refresh_row = self._claim_metrics_refresh(refreshes_table_name, worker_id)
        if refresh_row is None:
            return None

        try:
            dates_to_process, fingerprint = self._get_metrics_dates_to_calculate(
                aggregate_metrics_table_name, sessions_table_name, runs_table_name, refresh_row, rebuild_from
            )

            legacy_runs_by_day: Dict[date, List[Dict[str, Any]]] = {}
            legacy_runs_by_id: Dict[str, Dict[str, Any]] = {}
            if rebuild_from is not None:
                # Every session is read again, for the legacy runs a process of an earlier release saved since
                self._metrics_legacy_runs = None
            # Read once for every day until the v3.0.0 migration is stamped: no index finds one day's legacy runs. A
            # store created by 3.0 or 3.1 stamps no version, so they are read only while a read of every session found
            # some
            if (
                dates_to_process
                and self._metrics_legacy_runs is not False
                and packaging_version.parse(self.get_latest_schema_version(self.session_table_name) or "2.0.0")
                < packaging_version.parse("3.0.0")
            ):
                start_timestamp = int(
                    datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
                )
                end_timestamp = int(
                    datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
                if self._metrics_legacy_runs is None:
                    # The first read reads every session, so one that finds no legacy runs finds none anywhere
                    start_timestamp, end_timestamp = 0, max(end_timestamp, int(time.time()) + 1)
                legacy_runs_by_day, legacy_runs_by_id = self._get_metrics_legacy_runs(
                    sessions_table_name, runs_table_name, start_timestamp, end_timestamp
                )
                if not self._heartbeat_metrics_refresh(refreshes_table_name, worker_id):
                    return None
                if self._metrics_legacy_runs is None:
                    self._metrics_legacy_runs = bool(legacy_runs_by_id)
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
                    self._release_metrics_refresh(refreshes_table_name, worker_id, stopped=True)
                    return None
                if not self._calculate_date_metrics(
                    table_name,
                    aggregate_metrics_table_name,
                    sessions_table_name,
                    runs_table_name,
                    date_to_process,
                    legacy_runs_by_day.get(date_to_process, []),
                    legacy_runs_by_id,
                    refreshes_table_name,
                    worker_id,
                    should_stop,
                ):
                    if should_stop is not None and should_stop():
                        self._release_metrics_refresh(refreshes_table_name, worker_id, stopped=True)
                    return None
                calculated_dates.append(date_to_process)

            # A month row is read only once completed, so a month is built only once its last day can be completed
            month_starts = sorted(
                month_start
                for month_start in set(get_months_to_calculate_metrics_for(calculated_dates))
                | set(self._get_open_metrics_months(aggregate_metrics_table_name))
                if metrics_day_completed(metrics_month_end(month_start))
            )
            for month_start in month_starts:
                if should_stop is not None and should_stop():
                    self._release_metrics_refresh(refreshes_table_name, worker_id, stopped=True)
                    return None
                if not self._calculate_month_metrics(
                    table_name, aggregate_metrics_table_name, month_start, refreshes_table_name, worker_id
                ):
                    return None

        except Exception as e:
            self._release_metrics_refresh(refreshes_table_name, worker_id, error=database_error_message(e))
            raise

        self._release_metrics_refresh(
            refreshes_table_name, worker_id, fingerprint=fingerprint, claimed_fingerprint=refresh_row["fingerprint"]
        )

        if not calculated_dates:
            log_info("Metrics already calculated for all relevant dates.")
            return []

        log_debug("Updated metrics calculations")
        return calculated_dates

    def _get_metrics_counted_days(self, starting_date: Optional[date], ending_date: Optional[date]) -> List[date]:
        """Get the days in the given date range whose everyone row counts any session or run, oldest first. A day
        that counts nothing has no component metrics rows. A day whose only run is a regenerated one has its tokens
        but no count."""
        return [
            row["date"]
            for row in self._get_aggregate_metrics_items(
                self.aggregate_metrics_table_name,
                "daily",
                "",
                starting_date,
                ending_date,
                attributes=["date", *AGGREGATE_METRICS_COUNT_COLUMNS, "total_tokens"],
            )
            if any(row.get(column) for column in AGGREGATE_METRICS_COUNT_COLUMNS if column != "users_count")
            or (row.get("total_tokens") or 0) > 0
        ]

    def _get_metrics_by_owner(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of each user and day from the component metrics, in the shape of the metrics table."""
        table_name = self.component_metrics_table_name
        try:
            # Each day is read from its rows: only the days whose everyone row counts anything
            rows: List[Dict[str, Any]] = []
            for day in self._get_metrics_counted_days(starting_date, ending_date):
                rows.extend(self._get_component_metrics_rows(table_name, day, user_id, list(METRICS_BY_OWNER_FIELDS)))
        except self.client.exceptions.ResourceNotFoundException:
            return [], None
        if not rows:
            return [], None

        latest_updated_at = max((row["updated_at"] for row in rows if row.get("updated_at") is not None), default=None)
        return build_metrics_by_owner_from_rows(rows), latest_updated_at

    def _get_aggregate_metrics_rows(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the day rows of the aggregate metrics table in the shape of the metrics table: the everyone rows for
        ``""``, one user's rows for a name, and every user's rows for ``None``."""
        try:
            # Only what build_metrics_from_aggregate_metrics reads, so the maps of timings are never decoded
            rows = self._get_aggregate_metrics_items(
                self.aggregate_metrics_table_name,
                "daily",
                user_id,
                starting_date,
                ending_date,
                attributes=list(AGGREGATE_METRICS_ROWS_FIELDS),
            )
        except self.client.exceptions.ResourceNotFoundException:
            return [], None
        if user_id is None:
            rows = [row for row in rows if row["user_id"] != ""]
        # A day without sessions or runs keeps an everyone row of zeros, where agno_metrics kept no row. A day whose
        # only run is a regenerated one has its tokens but no count
        rows = [
            row
            for row in rows
            if any(row[column] for column in AGGREGATE_METRICS_COUNT_COLUMNS if column != "users_count")
            or row["total_tokens"] > 0
        ]
        rows.sort(key=lambda row: (row["date"], row["user_id"]))
        latest_updated_at = max((row["updated_at"] for row in rows if row.get("updated_at") is not None), default=None)
        return build_metrics_from_aggregate_metrics(rows), latest_updated_at

    def _get_metrics_rows(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of each user and day, as get_metrics returns them once the first calculate_metrics has
        finished: a user's from that user's rows, the runs with no user from their component metrics rows."""
        if user_id == "":
            return self._get_metrics_by_owner(starting_date, ending_date, user_id)
        metrics, latest_updated_at = self._get_aggregate_metrics_rows(starting_date, ending_date, user_id)
        if user_id is not None:
            return metrics, latest_updated_at

        unowned_metrics, unowned_updated_at = self._get_metrics_by_owner(starting_date, ending_date, "")
        latest_updated_at = max(
            (updated_at for updated_at in [latest_updated_at, unowned_updated_at] if updated_at is not None),
            default=None,
        )
        return sorted(metrics + unowned_metrics, key=lambda x: (x["date"], x["user_id"] or "")), latest_updated_at

    def _metrics_calculated(self, refreshes_table_name: str) -> bool:
        """Whether the first calculate_metrics has finished, so reads take the metrics tables over agno_metrics."""
        refresh_row = self._get_metrics_refresh_row(refreshes_table_name)[0]
        return refresh_row is not None and refresh_row["finished_at"] is not None

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Any], Optional[int]]:
        """
        Get metrics from the database.

        Metrics are read from the aggregate metrics and component metrics once the first calculate_metrics has finished,
        and from the deprecated metrics table until then. A read never calculates them: checking whether the sessions
        and runs changed reads every one of the last two days, so calculate_metrics does.

        Args:
            starting_date: The starting date to filter metrics by.
            ending_date: The ending date to filter metrics by.
            user_id: When set, returns only that user's bucket. ``None`` returns every bucket,
                including the unowned one.

        Returns:
            Tuple[List[Any], Optional[int]]: A tuple containing the metrics data and the timestamp of the latest
                update.

        Raises:
            Exception: If any error occurs while getting the metrics.
        """

        try:
            if self._metrics_calculated(self.metrics_refreshes_table_name):
                return self._get_metrics_rows(starting_date, ending_date, user_id)

            # Read without creating the table: it is no longer written
            table_name = self.metrics_table_name

            # Build query parameters
            scan_kwargs: Dict[str, Any] = {"TableName": table_name}

            if starting_date or ending_date:
                filter_expressions = []
                expression_values = {}

                if starting_date:
                    filter_expressions.append("#date >= :start_date")
                    expression_values[":start_date"] = {"S": starting_date.isoformat()}

                if ending_date:
                    filter_expressions.append("#date <= :end_date")
                    expression_values[":end_date"] = {"S": ending_date.isoformat()}

                scan_kwargs["FilterExpression"] = " AND ".join(filter_expressions)
                scan_kwargs["ExpressionAttributeNames"] = {"#date": "date"}
                scan_kwargs["ExpressionAttributeValues"] = expression_values

            # Execute scan
            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Convert to metrics data
            records = [record for record in (deserialize_from_dynamodb_item(item) for item in items) if record]
            # Records written before ownership existed hold a whole day, and only an
            # unscoped read sees them: an owner filter excludes them already
            if user_id is None:
                records = drop_legacy_metrics(records)

            metrics_data = []
            for metric_data in records:
                # Filter by user_id in-memory (user_id is not a key attribute)
                if user_id is not None and metric_data.get("user_id") != user_id:
                    continue
                # The empty-string bucket holds unowned sessions
                if metric_data.get("user_id") == "":
                    metric_data["user_id"] = None
                # Stored as an ISO string, and a string renders timezone-naive at the API layer
                metric_data["date"] = deserialize_metrics_date(metric_data.get("date"))
                metrics_data.append(metric_data)

            # Latest updated_at across the returned rows, like every other adapter
            latest_updated_at = None
            if metrics_data:
                latest_updated_at = max(metric.get("updated_at") or 0 for metric in metrics_data)

            return metrics_data, latest_updated_at

        except self.client.exceptions.ResourceNotFoundException:
            return [], None
        except Exception as e:
            log_error(f"Failed to get metrics: {str(e)}")
            raise e

    def get_metrics_by_date(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of every user, one row per day, matching the given date range.

        Read from the everyone rows of the aggregate metrics once the first calculate_metrics has finished, and from the
        deprecated metrics table until then.

        Args:
            starting_date: The starting date to filter metrics by.
            ending_date: The ending date to filter metrics by.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            if self._metrics_calculated(self.metrics_refreshes_table_name):
                return self._get_aggregate_metrics_rows(starting_date, ending_date, "")
            return super().get_metrics_by_date(starting_date, ending_date)

        except Exception as e:
            log_error(f"Failed to get metrics: {str(e)}")
            raise e

    def get_metrics_refresh_status(self) -> Optional[Dict[str, Any]]:
        """Get the status of the most recent calculate_metrics, from the metrics refreshes table.

        Returns:
            Optional[Dict[str, Any]]: The status ('running', 'completed' or 'failed'), when it started and finished,
                and its error. None before the first calculation.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            return metrics_refresh_status(*self._get_metrics_refresh_row(self.metrics_refreshes_table_name))

        except Exception as e:
            log_error(f"Failed to get metrics refresh status: {str(e)}")
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
            starting_date: The first day to total.
            ending_date: The last day to total.
            user_id: Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with no user.
            fields: The columns to total.
            use_month_rows: Total a calendar month inside the date range from its month aggregate metrics row, as one
                date.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each date, and when they were last updated.
        """
        aggregate_metrics_table_name = self.aggregate_metrics_table_name
        try:
            # The component metrics table keeps day rows only, so the runs with no user are read day by day
            full_months = metrics_full_months(starting_date, ending_date) if use_month_rows and user_id != "" else []
            month_starts: List[date] = []
            if full_months:
                # Only a completed month's row stands for its days; an open one, reopened by a day rebuilt since
                # or not yet built, is read from its days
                month_starts = [
                    row["date"]
                    for row in self._get_aggregate_metrics_items(
                        aggregate_metrics_table_name,
                        "monthly",
                        "",
                        full_months[0],
                        full_months[-1],
                        completed=True,
                        attributes=["date"],
                    )
                ]
            day_ranges = metrics_day_ranges(starting_date, ending_date, month_starts)
            days = [
                first_day + timedelta(days=offset)
                for first_day, last_day in day_ranges
                for offset in range((last_day - first_day).days + 1)
            ]

            rows: List[Dict[str, Any]] = []
            if user_id == "":
                # Every owner is read from the everyone rows and a user from the user's rows; the runs with no user
                # have no aggregate metrics row of their own, so they are read from their component rows
                counted_days = set(self._get_metrics_counted_days(starting_date, ending_date))
                for day in days:
                    if day in counted_days:
                        rows.extend(
                            self._get_component_metrics_rows(
                                self.component_metrics_table_name, day, "", metrics_rows_fields(fields)
                            )
                        )
            else:
                # The days of a completed month are read from its month row, so each run of days around them is read
                # on its own
                for first_day, last_day in day_ranges:
                    rows.extend(
                        self._get_aggregate_metrics_items(
                            aggregate_metrics_table_name,
                            "daily",
                            user_id or "",
                            first_day,
                            last_day,
                            attributes=metrics_rows_fields(fields),
                        )
                    )
                if month_starts:
                    rows.extend(
                        self._get_aggregate_metrics_items(
                            aggregate_metrics_table_name,
                            "monthly",
                            user_id or "",
                            month_starts[0],
                            month_starts[-1],
                            attributes=metrics_rows_fields(fields),
                        )
                    )
        except self.client.exceptions.ResourceNotFoundException:
            return [], None
        return total_metrics_rows(rows, starting_date, ending_date, fields, month_starts)

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
            starting_date: The first day to total.
            ending_date: The last day to total.
            user_id: Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with no user.
            fields: The columns to total. ``None`` totals all.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each day, and when they were last updated.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            fields = resolve_metrics_fields(fields)
            metrics, latest_updated_at = self._get_component_metrics_totals_by_date(
                starting_date, ending_date, user_id, fields
            )
            return [list_metrics_totals_models(day_totals) for day_totals in metrics], latest_updated_at

        except Exception as e:
            log_error(f"Failed to get component metrics: {str(e)}")
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
            starting_date: The first day to total.
            ending_date: The last day to total.
            user_id: Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with no user.
            fields: The columns to total. ``None`` totals all.

        Returns:
            Tuple[Dict[str, Any], Optional[int]]: The totals of the date range, and when they were last updated.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            fields = resolve_metrics_fields(fields)
            totals, latest_updated_at = self._get_component_metrics_totals_by_date(
                starting_date, ending_date, user_id, fields, use_month_rows=True
            )
            return list_metrics_totals_models(merge_metrics_totals(totals, fields)), latest_updated_at

        except Exception as e:
            log_error(f"Failed to get metrics totals: {str(e)}")
            raise e

    def get_metrics_versions(self, starting_date: date, ending_date: date) -> Optional[Dict[str, int]]:
        """Get the version of every everyone row of a day or a month of the aggregate metrics in the given date range.

        Args:
            starting_date: The first day of the date range.
            ending_date: The last day of the date range.

        Returns:
            Optional[Dict[str, int]]: The version of each everyone row, keyed by its aggregation period and date. The
                same again only while no calculation wrote a row of the date range. ``None`` until the first
                calculate_metrics has finished, or without an aggregate metrics table: a read would find no rows to
                total.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            if not self._metrics_calculated(self.metrics_refreshes_table_name):
                return None

            # The everyone rows of each period are keyed by the period alone, one consistent query each
            rows: List[Dict[str, Any]] = []
            for aggregation_period in ["daily", "monthly"]:
                rows.extend(
                    self._get_aggregate_metrics_items(
                        self.aggregate_metrics_table_name,
                        aggregation_period,
                        "",
                        starting_date,
                        ending_date,
                        attributes=["aggregation_period", "date", "version"],
                    )
                )
            return metrics_versions([SimpleNamespace(**row) for row in rows])

        except self.client.exceptions.ResourceNotFoundException:
            return None
        except Exception as e:
            log_error(f"Failed to get metrics versions: {str(e)}")
            raise e

    # --- Knowledge methods ---

    @staticmethod
    def _knowledge_row_is_visible(row: KnowledgeRow, user_id: Optional[str]) -> bool:
        """Unscoped callers see every row. Scoped callers see their own rows and unowned ones."""
        if user_id is None:
            return True
        owner = getattr(row, "user_id", None)
        return owner is None or owner == user_id

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): When set, only rows owned by this user are deleted. Unowned
                rows are shared content and are left alone.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table_name = self._get_table("knowledge")

            kwargs: Dict[str, Any] = {"TableName": table_name, "Key": {"id": {"S": id}}}
            if user_id is not None:
                kwargs["ConditionExpression"] = "user_id = :user_id"
                kwargs["ExpressionAttributeValues"] = {":user_id": {"S": user_id}}
            self.client.delete_item(**kwargs)

            log_debug(f"Deleted knowledge content {id}")

        except self.client.exceptions.ConditionalCheckFailedException:
            log_debug(f"Skipping delete of knowledge content {id}: not owned by {user_id}")

        except Exception as e:
            log_error(f"Failed to delete knowledge content {id}: {str(e)}")
            raise e

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): When set, the row is only returned if owned by this user or unowned.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.
        """
        try:
            table_name = self._get_table("knowledge")
            response = self.client.get_item(TableName=table_name, Key={"id": {"S": id}})

            item = response.get("Item")
            if not item:
                return None

            row = deserialize_knowledge_row(item)
            if not self._knowledge_row_is_visible(row, user_id):
                return None
            return row

        except Exception as e:
            log_error(f"Failed to get knowledge content {id}: {str(e)}")
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
            user_id (Optional[str]): When set, only rows owned by this user or unowned rows are returned.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table_name = self._get_table("knowledge")
            if table_name is None:
                return [], 0

            response = self.client.scan(TableName=table_name)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.client.scan(
                    TableName=table_name,
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            # Convert to knowledge rows
            knowledge_rows = []
            for item in items:
                try:
                    knowledge_row = deserialize_knowledge_row(item)
                    knowledge_rows.append(knowledge_row)
                except Exception as e:
                    log_error(f"Failed to deserialize knowledge row: {str(e)}")

            # Filter by user_id if provided
            if user_id is not None:
                knowledge_rows = [row for row in knowledge_rows if self._knowledge_row_is_visible(row, user_id)]

            # Apply linked_to filter if provided
            if linked_to is not None:
                knowledge_rows = [row for row in knowledge_rows if row.linked_to == linked_to]

            # Apply sorting
            if sort_by:
                reverse = sort_order == "desc"
                knowledge_rows = sorted(
                    knowledge_rows,
                    key=lambda x: getattr(x, sort_by, ""),
                    reverse=reverse,
                )

            # Get total count before pagination
            total_count = len(knowledge_rows)

            # Apply pagination
            if limit:
                start_index = 0
                if page and page > 1:
                    start_index = (page - 1) * limit
                knowledge_rows = knowledge_rows[start_index : start_index + limit]

            return knowledge_rows, total_count

        except Exception as e:
            log_error(f"Failed to get knowledge contents: {str(e)}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        try:
            table_name = self._get_table("knowledge", create_table_if_not_found=True)

            # A scoped write must not overwrite an item it does not own
            if knowledge_row.user_id is not None and knowledge_row.id:
                response = self.client.get_item(TableName=table_name, Key={"id": {"S": knowledge_row.id}})
                stored = response.get("Item")
                if stored is not None and stored.get("user_id", {}).get("S") != knowledge_row.user_id:
                    raise ValueError(f"Knowledge content {knowledge_row.id} not found")

            item = serialize_knowledge_row(knowledge_row)

            self.client.put_item(TableName=table_name, Item=item)

            return knowledge_row

        except Exception as e:
            log_error(f"Failed to upsert knowledge content {knowledge_row.id}: {str(e)}")
            raise e

    # --- Eval ---

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an eval run in the database.

        Args:
            eval_run (EvalRunRecord): The eval run to create.

        Returns:
            Optional[EvalRunRecord]: The created eval run, or None if the operation fails.

        Raises:
            Exception: If an error occurs during creation.
        """
        try:
            table_name = self._get_table("evals", create_table_if_not_found=True)

            item = serialize_eval_record(eval_run)
            current_time = int(datetime.now(timezone.utc).timestamp())
            item["created_at"] = {"N": str(current_time)}
            item["updated_at"] = {"N": str(current_time)}

            self.client.put_item(TableName=table_name, Item=item)

            return eval_run

        except Exception as e:
            log_error(f"Failed to create eval run: {str(e)}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str], user_id: Optional[str] = None) -> None:
        if not eval_run_ids or not self.eval_table_name:
            return

        try:
            if user_id is not None:
                # Only delete runs owned by this user.
                owned = []
                for eval_run_id in eval_run_ids:
                    response = self.client.get_item(TableName=self.eval_table_name, Key={"run_id": {"S": eval_run_id}})
                    item = response.get("Item")
                    if item is not None and item.get("user_id", {}).get("S") == user_id:
                        owned.append(eval_run_id)
                eval_run_ids = owned

            for i in range(0, len(eval_run_ids), DYNAMO_BATCH_SIZE_LIMIT):
                batch = eval_run_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]

                delete_requests = []
                for eval_run_id in batch:
                    delete_requests.append({"DeleteRequest": {"Key": {"run_id": {"S": eval_run_id}}}})

                batch_write_with_retry(self.client, {self.eval_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete eval runs: {str(e)}")
            raise e

    def get_eval_run_raw(self, eval_run_id: str, table: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        if not self.eval_table_name:
            return None

        try:
            response = self.client.get_item(TableName=self.eval_table_name, Key={"run_id": {"S": eval_run_id}})

            item = response.get("Item")
            if item:
                return deserialize_from_dynamodb_item(item)
            return None

        except Exception as e:
            log_error(f"Failed to get eval run {eval_run_id}: {str(e)}")
            raise e

    def get_eval_run(
        self,
        eval_run_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
        table: Optional[Any] = None,
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        if not self.eval_table_name:
            return None

        try:
            response = self.client.get_item(TableName=self.eval_table_name, Key={"run_id": {"S": eval_run_id}})

            item = response.get("Item")
            if not item:
                return None

            eval_item = deserialize_from_dynamodb_item(item)
            if user_id is not None and eval_item.get("user_id") != user_id:
                return None

            if not deserialize:
                return eval_item

            return EvalRunRecord.model_validate(eval_item)

        except Exception as e:
            log_error(f"Failed to get eval run {eval_run_id}: {str(e)}")
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
        try:
            table_name = self._get_table("evals")
            if table_name is None:
                return [] if deserialize else ([], 0)

            scan_kwargs = {"TableName": table_name}

            filter_expressions = []
            expression_values = {}

            if agent_id:
                filter_expressions.append("agent_id = :agent_id")
                expression_values[":agent_id"] = {"S": agent_id}

            if team_id:
                filter_expressions.append("team_id = :team_id")
                expression_values[":team_id"] = {"S": team_id}

            if workflow_id:
                filter_expressions.append("workflow_id = :workflow_id")
                expression_values[":workflow_id"] = {"S": workflow_id}

            if model_id:
                filter_expressions.append("model_id = :model_id")
                expression_values[":model_id"] = {"S": model_id}

            if user_id is not None:
                filter_expressions.append("user_id = :user_id")
                expression_values[":user_id"] = {"S": user_id}

            if eval_type is not None and len(eval_type) > 0:
                eval_type_conditions = []
                for i, et in enumerate(eval_type):
                    param_name = f":eval_type_{i}"
                    eval_type_conditions.append(f"eval_type = {param_name}")
                    expression_values[param_name] = {"S": str(et.value)}
                filter_expressions.append(f"({' OR '.join(eval_type_conditions)})")

            if filter_type is not None:
                if filter_type == EvalFilterType.AGENT:
                    filter_expressions.append("attribute_exists(agent_id)")
                elif filter_type == EvalFilterType.TEAM:
                    filter_expressions.append("attribute_exists(team_id)")
                elif filter_type == EvalFilterType.WORKFLOW:
                    filter_expressions.append("attribute_exists(workflow_id)")

            if filter_expressions:
                scan_kwargs["FilterExpression"] = " AND ".join(filter_expressions)

            if expression_values:
                scan_kwargs["ExpressionAttributeValues"] = expression_values  # type: ignore

            # Execute scan
            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Convert to eval data
            eval_data = []
            for item in items:
                eval_item = deserialize_from_dynamodb_item(item)
                if eval_item:
                    eval_data.append(eval_item)

            # Apply sorting
            eval_data = apply_sorting(eval_data, sort_by, sort_order)

            # Get total count before pagination
            total_count = len(eval_data)

            # Apply pagination
            eval_data = apply_pagination(eval_data, limit, page)

            if not deserialize:
                return eval_data, total_count

            eval_runs = []
            for eval_item in eval_data:
                eval_run = EvalRunRecord.model_validate(eval_item)
                eval_runs.append(eval_run)
            return eval_runs

        except Exception as e:
            log_error(f"Failed to get eval runs: {str(e)}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        if not self.eval_table_name:
            return None

        try:
            update_kwargs: Dict[str, Any] = dict(
                TableName=self.eval_table_name,
                Key={"run_id": {"S": eval_run_id}},
                UpdateExpression="SET #name = :name, updated_at = :updated_at",
                ExpressionAttributeNames={"#name": "name"},
                ExpressionAttributeValues={
                    ":name": {"S": name},
                    ":updated_at": {"N": str(int(time.time()))},
                },
                ReturnValues="ALL_NEW",
            )
            # Avoid upserting a phantom item when the run doesn't exist. Such an item carries
            # no eval_type, and every later read of the table fails on it.
            update_kwargs["ConditionExpression"] = "attribute_exists(run_id)"
            # Only rename if owned by this user.
            if user_id is not None:
                update_kwargs["ConditionExpression"] += " AND user_id = :user_id"
                update_kwargs["ExpressionAttributeValues"][":user_id"] = {"S": user_id}

            try:
                response = self.client.update_item(**update_kwargs)
            except self.client.exceptions.ConditionalCheckFailedException:
                return None

            item = response.get("Attributes")
            if item is None:
                return None

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            item = deserialize_from_dynamodb_item(item)
            return EvalRunRecord.model_validate(item) if deserialize else item

        except Exception as e:
            log_error(f"Failed to rename eval run {eval_run_id}: {str(e)}")
            raise e

    def update_eval_run_user_id(self, eval_run_id: str, user_id: str) -> None:
        """Set the owner (user_id) on an existing eval run.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            user_id (str): The owner to set.
        """
        if not self.eval_table_name:
            return

        try:
            self.client.update_item(
                TableName=self.eval_table_name,
                Key={"run_id": {"S": eval_run_id}},
                UpdateExpression="SET user_id = :user_id",
                # Avoid upserting a phantom item when the run doesn't exist.
                ConditionExpression="attribute_exists(run_id)",
                ExpressionAttributeValues={":user_id": {"S": user_id}},
            )

        except self.client.exceptions.ConditionalCheckFailedException:
            return

        except Exception as e:
            log_error(f"Failed to set owner on eval run {eval_run_id}: {str(e)}")
            raise e

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            table_name = self._get_table("traces", create_table_if_not_found=True)
            if table_name is None:
                return

            # Check if trace already exists
            response = self.client.get_item(
                TableName=table_name,
                Key={"trace_id": {"S": trace.trace_id}},
            )

            existing_item = response.get("Item")
            if existing_item:
                # Update existing trace
                existing = deserialize_from_dynamodb_item(existing_item)

                # Determine component level for name update priority
                def get_component_level(workflow_id, team_id, agent_id, name):
                    is_root_name = ".run" in name or ".arun" in name
                    if not is_root_name:
                        return 0
                    elif workflow_id:
                        return 3
                    elif team_id:
                        return 2
                    elif agent_id:
                        return 1
                    else:
                        return 0

                existing_level = get_component_level(
                    existing.get("workflow_id"),
                    existing.get("team_id"),
                    existing.get("agent_id"),
                    existing.get("name", ""),
                )
                new_level = get_component_level(trace.workflow_id, trace.team_id, trace.agent_id, trace.name)
                should_update_name = new_level > existing_level

                # Parse existing start_time to calculate correct duration
                existing_start_time_str = existing.get("start_time")
                if isinstance(existing_start_time_str, str):
                    existing_start_time = datetime.fromisoformat(existing_start_time_str.replace("Z", "+00:00"))
                else:
                    existing_start_time = trace.start_time

                recalculated_duration_ms = int((trace.end_time - existing_start_time).total_seconds() * 1000)

                # Build update expression
                update_parts = [
                    "end_time = :end_time",
                    "duration_ms = :duration_ms",
                    "#status = :status",
                ]
                expression_attr_names = {"#status": "status"}
                expression_attr_values: Dict[str, Any] = {
                    ":end_time": {"S": trace.end_time.isoformat()},
                    ":duration_ms": {"N": str(recalculated_duration_ms)},
                    ":status": {"S": trace.status},
                }

                if should_update_name:
                    update_parts.append("#name = :name")
                    expression_attr_names["#name"] = "name"
                    expression_attr_values[":name"] = {"S": trace.name}

                # Preserve existing non-null context values: only fill in fields
                # that the existing row left blank. Otherwise a later upsert from
                # a child span (e.g. a post-hook agent's run with a different
                # session_id) would overwrite the trace's already-correct context.
                if existing.get("run_id") is None and trace.run_id is not None:
                    update_parts.append("run_id = :run_id")
                    expression_attr_values[":run_id"] = {"S": trace.run_id}
                if existing.get("session_id") is None and trace.session_id is not None:
                    update_parts.append("session_id = :session_id")
                    expression_attr_values[":session_id"] = {"S": trace.session_id}
                if existing.get("user_id") is None and trace.user_id is not None:
                    update_parts.append("user_id = :user_id")
                    expression_attr_values[":user_id"] = {"S": trace.user_id}
                if existing.get("agent_id") is None and trace.agent_id is not None:
                    update_parts.append("agent_id = :agent_id")
                    expression_attr_values[":agent_id"] = {"S": trace.agent_id}
                if existing.get("team_id") is None and trace.team_id is not None:
                    update_parts.append("team_id = :team_id")
                    expression_attr_values[":team_id"] = {"S": trace.team_id}
                if existing.get("workflow_id") is None and trace.workflow_id is not None:
                    update_parts.append("workflow_id = :workflow_id")
                    expression_attr_values[":workflow_id"] = {"S": trace.workflow_id}

                self.client.update_item(
                    TableName=table_name,
                    Key={"trace_id": {"S": trace.trace_id}},
                    UpdateExpression="SET " + ", ".join(update_parts),
                    ExpressionAttributeNames=expression_attr_names,
                    ExpressionAttributeValues=expression_attr_values,
                )
            else:
                # Create new trace with initialized counters
                trace_dict = trace.to_dict()
                trace_dict["total_spans"] = 0
                trace_dict["error_count"] = 0
                item = serialize_to_dynamo_item(trace_dict)
                self.client.put_item(TableName=table_name, Item=item)

        except Exception as e:
            log_error(f"Error creating trace: {str(e)}")

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
            from agno.tracing.schemas import Trace

            table_name = self._get_table("traces")
            if table_name is None:
                return None

            if trace_id:
                # Direct lookup by primary key
                response = self.client.get_item(
                    TableName=table_name,
                    Key={"trace_id": {"S": trace_id}},
                )
                item = response.get("Item")
                if item:
                    trace_data = deserialize_from_dynamodb_item(item)
                    trace_data.setdefault("total_spans", 0)
                    trace_data.setdefault("error_count", 0)
                    return Trace.from_dict(trace_data)
                return None

            elif run_id:
                # Query using GSI
                response = self.client.query(
                    TableName=table_name,
                    IndexName="run_id-start_time-index",
                    KeyConditionExpression="run_id = :run_id",
                    ExpressionAttributeValues={":run_id": {"S": run_id}},
                    ScanIndexForward=False,  # Descending order
                    Limit=1,
                )
                items = response.get("Items", [])
                if items:
                    trace_data = deserialize_from_dynamodb_item(items[0])
                    # Use stored values (default to 0 if not present)
                    trace_data.setdefault("total_spans", 0)
                    trace_data.setdefault("error_count", 0)
                    return Trace.from_dict(trace_data)
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
            from agno.tracing.schemas import Trace

            table_name = self._get_table("traces")
            if table_name is None:
                return [], 0

            # Determine if we can use a GSI query or need to scan
            use_gsi = False
            gsi_name = None
            key_condition = None
            key_values: Dict[str, Any] = {}

            # Check for GSI-compatible filters (only one can be used as key condition)
            if session_id:
                use_gsi = True
                gsi_name = "session_id-start_time-index"
                key_condition = "session_id = :session_id"
                key_values[":session_id"] = {"S": session_id}
            elif user_id is not None:
                use_gsi = True
                gsi_name = "user_id-start_time-index"
                key_condition = "user_id = :user_id"
                key_values[":user_id"] = {"S": user_id}
            elif agent_id:
                use_gsi = True
                gsi_name = "agent_id-start_time-index"
                key_condition = "agent_id = :agent_id"
                key_values[":agent_id"] = {"S": agent_id}
            elif team_id:
                use_gsi = True
                gsi_name = "team_id-start_time-index"
                key_condition = "team_id = :team_id"
                key_values[":team_id"] = {"S": team_id}
            elif workflow_id:
                use_gsi = True
                gsi_name = "workflow_id-start_time-index"
                key_condition = "workflow_id = :workflow_id"
                key_values[":workflow_id"] = {"S": workflow_id}
            elif run_id:
                use_gsi = True
                gsi_name = "run_id-start_time-index"
                key_condition = "run_id = :run_id"
                key_values[":run_id"] = {"S": run_id}
            elif status:
                use_gsi = True
                gsi_name = "status-start_time-index"
                key_condition = "#status = :status"
                key_values[":status"] = {"S": status}

            # Build filter expression for additional filters
            filter_parts = []
            filter_values: Dict[str, Any] = {}
            expression_attr_names: Dict[str, str] = {}

            if start_time:
                filter_parts.append("start_time >= :start_time")
                filter_values[":start_time"] = {"S": start_time.isoformat()}
            if end_time:
                filter_parts.append("end_time <= :end_time")
                filter_values[":end_time"] = {"S": end_time.isoformat()}

            if status and gsi_name != "status-start_time-index":
                filter_parts.append("#status = :filter_status")
                filter_values[":filter_status"] = {"S": status}
                expression_attr_names["#status"] = "status"

            items = []
            if use_gsi and gsi_name and key_condition:
                # Use GSI query
                query_kwargs: Dict[str, Any] = {
                    "TableName": table_name,
                    "IndexName": gsi_name,
                    "KeyConditionExpression": key_condition,
                    "ExpressionAttributeValues": {**key_values, **filter_values},
                    "ScanIndexForward": False,  # Descending order by start_time
                }
                if gsi_name == "status-start_time-index":
                    expression_attr_names["#status"] = "status"
                if expression_attr_names:
                    query_kwargs["ExpressionAttributeNames"] = expression_attr_names
                if filter_parts:
                    query_kwargs["FilterExpression"] = " AND ".join(filter_parts)

                response = self.client.query(**query_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response:
                    query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.query(**query_kwargs)
                    items.extend(response.get("Items", []))
            else:
                # Use scan
                scan_kwargs: Dict[str, Any] = {"TableName": table_name}
                if filter_parts:
                    scan_kwargs["FilterExpression"] = " AND ".join(filter_parts)
                    scan_kwargs["ExpressionAttributeValues"] = filter_values
                if expression_attr_names:
                    scan_kwargs["ExpressionAttributeNames"] = expression_attr_names

                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response:
                    scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.scan(**scan_kwargs)
                    items.extend(response.get("Items", []))

            # Deserialize items
            traces_data = [deserialize_from_dynamodb_item(item) for item in items]

            # Sort by start_time descending
            traces_data.sort(key=lambda x: x.get("start_time", ""), reverse=True)

            # Get total count
            total_count = len(traces_data)

            # Apply pagination
            offset = (page - 1) * limit if page and limit else 0
            paginated_data = traces_data[offset : offset + limit] if limit else traces_data

            # Use stored total_spans and error_count (default to 0 if not present)
            traces = []
            for trace_data in paginated_data:
                # Use stored values - these are updated by create_spans
                trace_data.setdefault("total_spans", 0)
                trace_data.setdefault("error_count", 0)
                traces.append(Trace.from_dict(trace_data))

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
                Each dict contains: session_id, user_id, agent_id, team_id, workflow_id, total_traces,
                first_trace_at, last_trace_at.
        """
        if group_by != "session":
            raise NotImplementedError(
                f"get_trace_stats with group_by={group_by!r} is not supported by {self.__class__.__name__}. "
                "Only the default 'session' grouping is available."
            )

        try:
            table_name = self._get_table("traces")
            if table_name is None:
                return [], 0

            # Fetch all traces and aggregate in memory (DynamoDB doesn't support GROUP BY)
            scan_kwargs: Dict[str, Any] = {"TableName": table_name}

            # Build filter expression
            filter_parts = []
            filter_values: Dict[str, Any] = {}

            if user_id is not None:
                filter_parts.append("user_id = :user_id")
                filter_values[":user_id"] = {"S": user_id}
            if agent_id:
                filter_parts.append("agent_id = :agent_id")
                filter_values[":agent_id"] = {"S": agent_id}
            if team_id:
                filter_parts.append("team_id = :team_id")
                filter_values[":team_id"] = {"S": team_id}
            if workflow_id:
                filter_parts.append("workflow_id = :workflow_id")
                filter_values[":workflow_id"] = {"S": workflow_id}
            if start_time:
                filter_parts.append("created_at >= :start_time")
                filter_values[":start_time"] = {"S": start_time.isoformat()}
            if end_time:
                filter_parts.append("created_at <= :end_time")
                filter_values[":end_time"] = {"S": end_time.isoformat()}

            # Filter for records with session_id
            filter_parts.append("attribute_exists(session_id)")

            if filter_parts:
                scan_kwargs["FilterExpression"] = " AND ".join(filter_parts)
            if filter_values:
                scan_kwargs["ExpressionAttributeValues"] = filter_values

            # Scan all matching traces
            items = []
            response = self.client.scan(**scan_kwargs)
            items.extend(response.get("Items", []))

            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Aggregate by session_id
            session_stats: Dict[str, Dict[str, Any]] = {}
            for item in items:
                trace_data = deserialize_from_dynamodb_item(item)
                session_id = trace_data.get("session_id")
                if not session_id:
                    continue

                if session_id not in session_stats:
                    session_stats[session_id] = {
                        "session_id": session_id,
                        "user_id": trace_data.get("user_id"),
                        "agent_id": trace_data.get("agent_id"),
                        "team_id": trace_data.get("team_id"),
                        "workflow_id": trace_data.get("workflow_id"),
                        "total_traces": 0,
                        "first_trace_at": trace_data.get("created_at"),
                        "last_trace_at": trace_data.get("created_at"),
                    }

                session_stats[session_id]["total_traces"] += 1

                created_at = trace_data.get("created_at")
                if (
                    created_at
                    and session_stats[session_id]["first_trace_at"]
                    and session_stats[session_id]["last_trace_at"]
                ):
                    if created_at < session_stats[session_id]["first_trace_at"]:
                        session_stats[session_id]["first_trace_at"] = created_at
                    if created_at > session_stats[session_id]["last_trace_at"]:
                        session_stats[session_id]["last_trace_at"] = created_at

            # Convert to list and sort by last_trace_at descending
            stats_list = list(session_stats.values())
            stats_list.sort(key=lambda x: x.get("last_trace_at", ""), reverse=True)

            # Convert datetime strings to datetime objects
            for stat in stats_list:
                first_trace_at = stat["first_trace_at"]
                last_trace_at = stat["last_trace_at"]
                if isinstance(first_trace_at, str):
                    stat["first_trace_at"] = datetime.fromisoformat(first_trace_at.replace("Z", "+00:00"))
                if isinstance(last_trace_at, str):
                    stat["last_trace_at"] = datetime.fromisoformat(last_trace_at.replace("Z", "+00:00"))

            # Get total count
            total_count = len(stats_list)

            # Apply pagination
            offset = (page - 1) * limit if page and limit else 0
            paginated_stats = stats_list[offset : offset + limit] if limit else stats_list

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
            table_name = self._get_table("spans", create_table_if_not_found=True)
            if table_name is None:
                return

            span_dict = span.to_dict()
            # Serialize attributes as JSON string
            if "attributes" in span_dict and isinstance(span_dict["attributes"], dict):
                span_dict["attributes"] = json.dumps(span_dict["attributes"])

            item = serialize_to_dynamo_item(span_dict)
            self.client.put_item(TableName=table_name, Item=item)

            # Increment total_spans and error_count on trace
            traces_table_name = self._get_table("traces")
            if traces_table_name:
                try:
                    update_expr = "ADD total_spans :inc"
                    expr_values: Dict[str, Any] = {":inc": {"N": "1"}}

                    if span.status_code == "ERROR":
                        update_expr += ", error_count :inc"

                    self.client.update_item(
                        TableName=traces_table_name,
                        Key={"trace_id": {"S": span.trace_id}},
                        UpdateExpression=update_expr,
                        ExpressionAttributeValues=expr_values,
                    )
                except Exception as update_error:
                    log_debug(f"Could not update trace span counts: {update_error}")

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
            table_name = self._get_table("spans", create_table_if_not_found=True)
            if table_name is None:
                return

            for i in range(0, len(spans), DYNAMO_BATCH_SIZE_LIMIT):
                batch = spans[i : i + DYNAMO_BATCH_SIZE_LIMIT]
                put_requests = []

                for span in batch:
                    span_dict = span.to_dict()
                    # Serialize attributes as JSON string
                    if "attributes" in span_dict and isinstance(span_dict["attributes"], dict):
                        span_dict["attributes"] = json.dumps(span_dict["attributes"])

                    item = serialize_to_dynamo_item(span_dict)
                    put_requests.append({"PutRequest": {"Item": item}})

                if put_requests:
                    batch_write_with_retry(self.client, {table_name: put_requests})

            # Update trace with total_spans and error_count using ADD (atomic increment)
            trace_id = spans[0].trace_id
            spans_count = len(spans)
            error_count = sum(1 for s in spans if s.status_code == "ERROR")

            traces_table_name = self._get_table("traces")
            if traces_table_name:
                try:
                    # Use ADD for atomic increment - works even if attributes don't exist yet
                    update_expr = "ADD total_spans :spans_inc"
                    expr_values: Dict[str, Any] = {":spans_inc": {"N": str(spans_count)}}

                    if error_count > 0:
                        update_expr += ", error_count :error_inc"
                        expr_values[":error_inc"] = {"N": str(error_count)}

                    self.client.update_item(
                        TableName=traces_table_name,
                        Key={"trace_id": {"S": trace_id}},
                        UpdateExpression=update_expr,
                        ExpressionAttributeValues=expr_values,
                    )
                except Exception as update_error:
                    log_debug(f"Could not update trace span counts: {update_error}")

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
            from agno.tracing.schemas import Span

            table_name = self._get_table("spans")
            if table_name is None:
                return None

            response = self.client.get_item(
                TableName=table_name,
                Key={"span_id": {"S": span_id}},
            )

            item = response.get("Item")
            if item:
                span_data = deserialize_from_dynamodb_item(item)
                # Deserialize attributes from JSON string
                if "attributes" in span_data and isinstance(span_data["attributes"], str):
                    span_data["attributes"] = json.loads(span_data["attributes"])
                return Span.from_dict(span_data)
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
            from agno.tracing.schemas import Span

            table_name = self._get_table("spans")
            if table_name is None:
                return []

            items = []

            if trace_id:
                # Use GSI query
                query_kwargs: Dict[str, Any] = {
                    "TableName": table_name,
                    "IndexName": "trace_id-start_time-index",
                    "KeyConditionExpression": "trace_id = :trace_id",
                    "ExpressionAttributeValues": {":trace_id": {"S": trace_id}},
                }
                if limit:
                    query_kwargs["Limit"] = limit

                response = self.client.query(**query_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response and (limit is None or len(items) < limit):
                    query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.query(**query_kwargs)
                    items.extend(response.get("Items", []))

            elif parent_span_id:
                # Use GSI query
                query_kwargs = {
                    "TableName": table_name,
                    "IndexName": "parent_span_id-start_time-index",
                    "KeyConditionExpression": "parent_span_id = :parent_span_id",
                    "ExpressionAttributeValues": {":parent_span_id": {"S": parent_span_id}},
                }
                if limit:
                    query_kwargs["Limit"] = limit

                response = self.client.query(**query_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response and (limit is None or len(items) < limit):
                    query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.query(**query_kwargs)
                    items.extend(response.get("Items", []))

            else:
                # Scan all spans
                scan_kwargs: Dict[str, Any] = {"TableName": table_name}
                if limit:
                    scan_kwargs["Limit"] = limit

                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response and (limit is None or len(items) < limit):
                    scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.scan(**scan_kwargs)
                    items.extend(response.get("Items", []))

            # Deserialize items
            spans = []
            for item in items[:limit] if limit else items:
                span_data = deserialize_from_dynamodb_item(item)
                # Deserialize attributes from JSON string
                if "attributes" in span_data and isinstance(span_data["attributes"], str):
                    span_data["attributes"] = json.loads(span_data["attributes"])
                spans.append(Span.from_dict(span_data))

            return spans

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
        raise NotImplementedError("Learning methods not yet implemented for DynamoDb")

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
        raise NotImplementedError("Learning methods not yet implemented for DynamoDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for DynamoDb")

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
        raise NotImplementedError("Learning methods not yet implemented for DynamoDb")
