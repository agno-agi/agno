import json
import time
from datetime import date, datetime, timedelta, timezone
from itertools import islice
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Tuple, Union, cast
from uuid import uuid4

from packaging import version as packaging_version

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.firestore.utils import (
    METRICS_IN_LIST_LIMIT,
    aggregate_metrics_record_id,
    apply_pagination,
    apply_sorting,
    component_metrics_record_id,
    create_collection_indexes,
    reopen_metrics_day,
    reopen_metrics_days_from,
    reopen_metrics_month,
)
from agno.db.migrations.manager import MigrationManager
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import (
    AGGREGATE_METRICS_COUNT_COLUMNS,
    AGGREGATE_METRICS_ROWS_FIELDS,
    METRICS_BATCH_SIZE,
    METRICS_BY_OWNER_FIELDS,
    METRICS_LOCK_SECONDS,
    METRICS_REFRESH_ID,
    METRICS_STOPPED_ERROR,
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
    deserialize_metrics_row,
    deserialize_run,
    deserialize_session,
    deserialize_session_json_fields,
    deserialize_sessions,
    drop_legacy_metrics,
    filter_context_runs,
    get_metrics_legacy_runs,
    get_metrics_reopen_session_ids,
    get_months_to_calculate_metrics_for,
    list_metrics_totals_models,
    merge_metrics_totals,
    merge_runs_table_with_legacy_blob,
    metrics_calculation_enabled,
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
    serialize_metrics_row,
    total_metrics_rows,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    from google.api_core.exceptions import (  # type: ignore[import-untyped]
        Aborted,
        AlreadyExists,
        FailedPrecondition,
        NotFound,
    )
    from google.cloud.firestore import (  # type: ignore[import-untyped]
        DELETE_FIELD,
        Client,
        FieldFilter,
        Increment,
        transactional,
    )
except ImportError:
    raise ImportError(
        "`google-cloud-firestore` not installed. Please install it using `pip install google-cloud-firestore`"
    )


# Firestore batched writes have a hard 500-operation limit per commit.
FIRESTORE_BATCH_LIMIT = 500


class FirestoreDb(BaseDb):
    def __init__(
        self,
        db_client: Optional[Client] = None,
        project_id: Optional[str] = None,
        session_collection: Optional[str] = None,
        runs_collection: Optional[str] = None,
        memory_collection: Optional[str] = None,
        metrics_collection: Optional[str] = None,
        component_metrics_collection: Optional[str] = None,
        aggregate_metrics_collection: Optional[str] = None,
        metrics_refreshes_collection: Optional[str] = None,
        eval_collection: Optional[str] = None,
        knowledge_collection: Optional[str] = None,
        traces_collection: Optional[str] = None,
        spans_collection: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a Firestore database.

        Args:
            db_client (Optional[Client]): The Firestore client to use.
            project_id (Optional[str]): The GCP project ID for Firestore.
            session_collection (Optional[str]): Name of the collection to store sessions.
            runs_collection (Optional[str]): Name of the collection to store runs (one document per run).
            memory_collection (Optional[str]): Name of the collection to store memories.
            metrics_collection (Optional[str]): Name of the collection to store metrics.
            component_metrics_collection (Optional[str]): Name of the collection to store the metrics of each agent,
                team and workflow.
            aggregate_metrics_collection (Optional[str]): Name of the collection to store the metrics of each user.
            metrics_refreshes_collection (Optional[str]): Name of the collection to store the metrics refreshes.
            eval_collection (Optional[str]): Name of the collection to store evaluation runs.
            knowledge_collection (Optional[str]): Name of the collection to store knowledge documents.
            traces_collection (Optional[str]): Name of the collection to store traces.
            spans_collection (Optional[str]): Name of the collection to store spans.
            id (Optional[str]): ID of the database.

        Raises:
            ValueError: If neither project_id nor db_client is provided.
        """
        if id is None:
            seed = project_id or str(db_client)
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_collection,
            runs_table=runs_collection,
            memory_table=memory_collection,
            metrics_table=metrics_collection,
            component_metrics_table=component_metrics_collection,
            aggregate_metrics_table=aggregate_metrics_collection,
            metrics_refreshes_table=metrics_refreshes_collection,
            eval_table=eval_collection,
            knowledge_table=knowledge_collection,
            traces_table=traces_collection,
            spans_table=spans_collection,
        )

        if metrics_collection is not None:
            log_warning(
                "metrics_collection is deprecated; use component_metrics_collection and aggregate_metrics_collection."
            )

        _client: Optional[Client] = db_client
        if _client is None and project_id is not None:
            _client = Client(project=project_id)
        if _client is None:
            raise ValueError("One of project_id or db_client must be provided")

        self.project_id: Optional[str] = project_id
        self.db_client: Client = _client

        # Zero means never refreshed; get_metrics uses this to refresh lazily, at most once per minute.
        # stop_metrics_refresh_on_read sets it to infinity, so reads never calculate
        self._metrics_refreshed_at: float = 0.0
        # The days whose metrics a write could not reopen, retried by the next write
        self._metrics_days_not_reopened: Set[date] = set()

    # -- DB methods --

    def table_exists(self, table_name: str) -> bool:
        """Check if a collection with the given name exists in the Firestore database.

        Args:
            table_name: Name of the collection to check

        Returns:
            bool: True if the collection exists in the database, False otherwise
        """
        return table_name in self.db_client.list_collections()

    def _get_collection(self, table_type: str, create_collection_if_not_found: Optional[bool] = True):
        """Get or create a collection based on table type.

        Args:
            table_type (str): The type of table to get or create.
            create_collection_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            CollectionReference: The collection reference.
        """
        if table_type == "sessions":
            if self.session_table_name is None:
                raise ValueError("Session collection was not provided on initialization")
            self.session_collection = self._get_or_create_collection(
                collection_name=self.session_table_name,
                collection_type="sessions",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.session_collection

        if table_type == "runs":
            if self.runs_table_name is None:
                raise ValueError("Runs collection was not provided on initialization")
            self.runs_collection = self._get_or_create_collection(
                collection_name=self.runs_table_name,
                collection_type="runs",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.runs_collection

        if table_type == "memories":
            if self.memory_table_name is None:
                raise ValueError("Memory collection was not provided on initialization")
            self.memory_collection = self._get_or_create_collection(
                collection_name=self.memory_table_name,
                collection_type="memories",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.memory_collection

        if table_type == "metrics":
            if self.metrics_table_name is None:
                raise ValueError("Metrics collection was not provided on initialization")
            self.metrics_collection = self._get_or_create_collection(
                collection_name=self.metrics_table_name,
                collection_type="metrics",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.metrics_collection

        if table_type == "component_metrics":
            if self.component_metrics_table_name is None:
                raise ValueError("Component metrics collection was not provided on initialization")
            self.component_metrics_collection = self._get_or_create_collection(
                collection_name=self.component_metrics_table_name,
                collection_type="component_metrics",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.component_metrics_collection

        if table_type == "aggregate_metrics":
            if self.aggregate_metrics_table_name is None:
                raise ValueError("Aggregate metrics collection was not provided on initialization")
            self.aggregate_metrics_collection = self._get_or_create_collection(
                collection_name=self.aggregate_metrics_table_name,
                collection_type="aggregate_metrics",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.aggregate_metrics_collection

        if table_type == "metrics_refreshes":
            if self.metrics_refreshes_table_name is None:
                raise ValueError("Metrics refreshes collection was not provided on initialization")
            self.metrics_refreshes_collection = self._get_or_create_collection(
                collection_name=self.metrics_refreshes_table_name,
                collection_type="metrics_refreshes",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.metrics_refreshes_collection

        if table_type == "evals":
            if self.eval_table_name is None:
                raise ValueError("Eval collection was not provided on initialization")
            self.eval_collection = self._get_or_create_collection(
                collection_name=self.eval_table_name,
                collection_type="evals",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.eval_collection

        if table_type == "knowledge":
            if self.knowledge_table_name is None:
                raise ValueError("Knowledge collection was not provided on initialization")
            self.knowledge_collection = self._get_or_create_collection(
                collection_name=self.knowledge_table_name,
                collection_type="knowledge",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.knowledge_collection

        if table_type == "traces":
            if self.trace_table_name is None:
                raise ValueError("Traces collection was not provided on initialization")
            self.traces_collection = self._get_or_create_collection(
                collection_name=self.trace_table_name,
                collection_type="traces",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.traces_collection

        if table_type == "spans":
            # Ensure traces collection exists first (spans reference traces)
            if create_collection_if_not_found:
                self._get_collection("traces", create_collection_if_not_found=True)
            if self.span_table_name is None:
                raise ValueError("Spans collection was not provided on initialization")
            self.spans_collection = self._get_or_create_collection(
                collection_name=self.span_table_name,
                collection_type="spans",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.spans_collection

        raise ValueError(f"Unknown table type: {table_type}")

    def _get_or_create_collection(
        self, collection_name: str, collection_type: str, create_collection_if_not_found: Optional[bool] = True
    ):
        """Get or create a collection with proper indexes.

        Args:
            collection_name (str): The name of the collection to get or create.
            collection_type (str): The type of collection to get or create.
            create_collection_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Optional[CollectionReference]: The collection reference.
        """
        try:
            collection_ref = self.db_client.collection(collection_name)

            if not hasattr(self, f"_{collection_name}_initialized"):
                if not create_collection_if_not_found:
                    return None
                # A collection exists only while it holds a document
                table_created = collection_type == "sessions" and not list(
                    collection_ref.limit(1).select(["session_id"]).stream()
                )
                create_collection_indexes(self.db_client, collection_name, collection_type)
                # Store the schema version for the created sessions collection, which holds no legacy runs for metrics
                if table_created:
                    latest_schema_version = MigrationManager(self).latest_schema_version
                    # Created only when none is stamped, as a collection is empty again whenever its
                    # sessions are deleted
                    try:
                        self.db_client.collection(self.versions_table_name).document(collection_name).create(
                            {
                                "table_name": collection_name,
                                "version": latest_schema_version.public,
                                "updated_at": int(time.time()),
                            }
                        )
                    except AlreadyExists:
                        pass
                setattr(self, f"_{collection_name}_initialized", True)

            return collection_ref

        except Exception as e:
            log_error(f"Error getting collection {collection_name}: {str(e)}")
            raise

    def cleanup_legacy_runs_field(self, force: bool = False) -> bool:
        """Unset the legacy ``runs`` field from session documents.

        The v3.0.0 migration intentionally leaves the legacy ``runs`` field on
        session documents as a backup. Once you have verified the migration
        and taken a backup, call this to reclaim the storage.

        Args:
            force: If True, unset the field even on sessions that still hold a
                non-null ``runs`` array (a sign that they were not migrated).
                Defaults to False.

        Returns:
            True if any documents were touched, False if there was nothing to
            clean up.
        """
        collection_ref = self._get_collection(table_type="sessions")
        if collection_ref is None:
            log_info(f"{self.session_table_name} collection does not exist, nothing to clean up")
            return False

        # Pre-flight: refuse if any session still has a non-empty legacy `runs` value
        if not force:
            pending = 0
            for doc in collection_ref.stream():
                data = doc.to_dict() or {}
                runs_val = data.get("runs")
                if runs_val:
                    pending += 1
            if pending > 0:
                raise RuntimeError(
                    f"Refusing to unset {self.session_table_name}.runs: {pending} session(s) still have "
                    "non-null `runs` content. Run MigrationManager(db).up() first, or pass force=True."
                )

        log_info(f"Unsetting legacy runs field from {self.session_table_name} documents")
        # Firestore's 500-op-per-batch hard limit — chunk to avoid
        # INVALID_ARGUMENT on installs with many sessions.
        batch = self.db_client.batch()
        touched = 0
        in_batch = 0
        for doc in collection_ref.stream():
            data = doc.to_dict() or {}
            if "runs" in data:
                batch.update(doc.reference, {"runs": DELETE_FIELD})
                touched += 1
                in_batch += 1
                if in_batch >= FIRESTORE_BATCH_LIMIT:
                    batch.commit()
                    batch = self.db_client.batch()
                    in_batch = 0
        if in_batch > 0:
            batch.commit()
        log_info(f"Unset runs on {touched} session document(s)")
        return touched > 0

    # -- Run methods --
    def _get_session_runs_docs(self, runs_collection_ref, session_id: str) -> List[Dict[str, Any]]:
        """Get the raw run_data dicts for the given session, in insertion order."""
        query = (
            runs_collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
            .order_by("run_index")
            .order_by("created_at")
        )
        return [doc.to_dict().get("run_data") for doc in query.stream() if doc.exists]

    def _get_sessions_runs(self, session_ids: List[str]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """Run dicts for several sessions in one read, used by the search fallback."""
        runs_collection_ref = self._get_collection(table_type="runs", create_collection_if_not_found=False)
        if runs_collection_ref is None:
            return {}
        return self._get_sessions_runs_docs(runs_collection_ref, session_ids)

    def _get_sessions_runs_docs(self, runs_collection_ref, session_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Get the raw run_data dicts for several sessions, grouped by session_id.

        Firestore's ``in`` filter caps at 30 values per query, so we chunk.
        """
        if not session_ids:
            return {}
        runs_buffer: Dict[str, List[Any]] = {}
        # Chunk to fit Firestore's `in` query limit (30)
        for start in range(0, len(session_ids), 30):
            chunk = session_ids[start : start + 30]
            query = runs_collection_ref.where(filter=FieldFilter("session_id", "in", chunk))
            for doc in query.stream():
                data = doc.to_dict() or {}
                sid = data.get("session_id")
                run_data = data.get("run_data")
                if sid is None or run_data is None:
                    continue
                runs_buffer.setdefault(sid, []).append(
                    (data.get("run_index") or 0, data.get("created_at") or 0, run_data)
                )
        # Sort each list by (run_index, created_at)
        runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
        for sid, items in runs_buffer.items():
            items.sort(key=lambda t: (t[0], t[1]))
            runs_by_session[sid] = [t[2] for t in items]
        return runs_by_session

    def upsert_run(
        self,
        run: Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]],
        session_id: str,
        user_id: Optional[str] = None,
        run_index: Optional[int] = None,
    ) -> None:
        """Upsert a single run document into the runs collection (O(1) operation).

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
            runs_collection_ref = self._get_collection(table_type="runs", create_collection_if_not_found=True)
            if runs_collection_ref is None:
                return

            row = build_single_run_row(
                run=run,
                session_id=session_id,
                user_id=user_id,
                run_index=run_index,
            )

            # Preserve the original run_index if the doc already exists
            doc_ref = runs_collection_ref.document(row["run_id"])
            snapshot = doc_ref.get()
            if snapshot.exists:
                existing = snapshot.to_dict() or {}
                if "run_index" in existing:
                    row["run_index"] = existing["run_index"]
                # The stored created_at, which a resumed run keeps
                if existing.get("created_at") is not None:
                    row["created_at"] = existing["created_at"]

            doc_ref.set(row)
            self._reopen_metrics_days([row["created_at"]])
        except Exception as e:
            log_error(f"Exception upserting run into runs collection: {str(e)}")
            raise e

    def get_run(
        self, run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]]]:
        """Read a single run from the runs collection."""
        try:
            collection_ref = self._get_collection(table_type="runs")
            if collection_ref is None:
                return None
            doc = collection_ref.document(run_id).get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            if not deserialize:
                return data
            return deserialize_run(data.get("run_type"), data["run_data"])
        except Exception as e:
            log_error(f"Exception reading from runs collection: {str(e)}")
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
        """Get all runs matching the given filters."""
        try:
            collection_ref = self._get_collection(table_type="runs")
            if collection_ref is None:
                return [] if deserialize else ([], 0)

            query = collection_ref
            if session_id is not None:
                query = query.where(filter=FieldFilter("session_id", "==", session_id))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id is not None:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id is not None:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if workflow_id is not None:
                query = query.where(filter=FieldFilter("workflow_id", "==", workflow_id))
            if status is not None:
                status_value = status.value if isinstance(status, RunStatus) else status
                query = query.where(filter=FieldFilter("status", "==", status_value))

            if sort_by is None:
                query = query.order_by("run_index").order_by("created_at")
            else:
                query = apply_sorting(query, sort_by, sort_order)

            all_docs = [doc.to_dict() for doc in query.stream() if doc.exists]
            total_count = len(all_docs)

            if limit is not None and page is not None:
                start_index = (page - 1) * limit
                run_rows = all_docs[start_index : start_index + limit]
            elif limit is not None:
                run_rows = all_docs[:limit]
            else:
                run_rows = all_docs

            if not deserialize:
                return run_rows, total_count
            return [deserialize_run(d.get("run_type"), d["run_data"]) for d in run_rows]
        except Exception as e:
            log_error(f"Exception reading from runs collection: {str(e)}")
            raise e

    def _scrub_run_ids_from_session_legacy_blob(self, session_id: str, run_ids: set) -> None:
        """Remove ``run_ids`` from the given session's legacy ``runs`` array.

        Partial-migration hygiene: v3 copied runs into their own collection but
        preserved the embedded ``runs`` array on the session doc as a backup.
        Deleting run docs alone leaves that array intact and the read path's
        ``merge_runs_table_with_legacy_blob`` resurrects the ghost.
        """
        if not run_ids or not session_id:
            return
        try:
            sessions_ref = self._get_collection(table_type="sessions")
            if sessions_ref is None:
                return
            session_ref = sessions_ref.document(session_id)
            snapshot = session_ref.get()
            if not snapshot.exists:
                return
            data = snapshot.to_dict() or {}
            legacy = data.get("runs")
            if not isinstance(legacy, list):
                return
            kept = [r for r in legacy if not (isinstance(r, dict) and r.get("run_id") in run_ids)]
            if len(kept) != len(legacy):
                session_ref.update({"runs": kept})
        except Exception:
            log_debug("legacy-runs scrub failed; primary delete still succeeded", exc_info=True)

    def delete_run(self, run_id: str) -> bool:
        """Delete a single run from the runs collection."""
        try:
            collection_ref = self._get_collection(table_type="runs")
            if collection_ref is None:
                return False
            doc_ref = collection_ref.document(run_id)
            snapshot = doc_ref.get()
            if not snapshot.exists:
                return False
            sid = (snapshot.to_dict() or {}).get("session_id")
            doc_ref.delete()
            if sid:
                self._scrub_run_ids_from_session_legacy_blob(sid, {run_id})
            return True
        except Exception as e:
            log_error(f"Error deleting run: {str(e)}")
            raise e

    def delete_runs(self, run_ids: List[str]) -> None:
        """Delete all given runs from the runs collection."""
        try:
            collection_ref = self._get_collection(table_type="runs")
            if collection_ref is None:
                return
            # Collect session_id → run_ids before deleting so we can scrub the
            # legacy blob on each affected session.
            runs_by_session: Dict[str, set] = {}
            for rid in run_ids:
                snap = collection_ref.document(rid).get()
                if not snap.exists:
                    continue
                sid = (snap.to_dict() or {}).get("session_id")
                if sid:
                    runs_by_session.setdefault(sid, set()).add(rid)

            # Firestore batched writes have a hard 500-op limit — chunk to
            # avoid ``INVALID_ARGUMENT`` on bulk deletes.
            deleted = 0
            for start in range(0, len(run_ids), FIRESTORE_BATCH_LIMIT):
                chunk = run_ids[start : start + FIRESTORE_BATCH_LIMIT]
                batch = self.db_client.batch()
                for rid in chunk:
                    batch.delete(collection_ref.document(rid))
                batch.commit()
                deleted += len(chunk)

            for sid, rids in runs_by_session.items():
                self._scrub_run_ids_from_session_legacy_blob(sid, rids)

            log_debug(f"Successfully deleted {deleted} runs")
        except Exception as e:
            log_error(f"Error deleting runs: {str(e)}")
            raise e

    # -- Session methods --

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session from the database.

        Args:
            session_id (str): The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            bool: True if the session was deleted, False otherwise.

        Raises:
            Exception: If there is an error deleting the session.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")
            runs_collection_ref = self._get_collection(table_type="runs", create_collection_if_not_found=False)

            query = collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            docs = query.stream()

            for doc in docs:
                doc.reference.delete()

                # Cascade-delete the session's runs, chunked to Firestore's
                # 500-op-per-commit limit so sessions with many runs don't blow
                # the batch (mirrors delete_sessions).
                if runs_collection_ref is not None:
                    runs_query = runs_collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
                    batch = self.db_client.batch()
                    in_batch = 0
                    for run_doc in runs_query.stream():
                        batch.delete(run_doc.reference)
                        in_batch += 1
                        if in_batch >= FIRESTORE_BATCH_LIMIT:
                            batch.commit()
                            batch = self.db_client.batch()
                            in_batch = 0
                    if in_batch > 0:
                        batch.commit()

                log_debug(f"Successfully deleted session with session_id: {session_id}")
                return True

            log_debug(f"No session found to delete with session_id: {session_id}")
            return False

        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            raise e

    def get_latest_schema_version(self, table_name: str = "") -> Optional[str]:
        """Get the schema version stamped for the given table.

        Defaults to "2.0.0" when nothing is stamped so the MigrationManager
        runs migrations instead of skipping the table.
        """
        doc = self.db_client.collection(self.versions_table_name).document(table_name).get()
        if not doc.exists:
            return "2.0.0"
        return (doc.to_dict() or {}).get("version") or "2.0.0"

    def upsert_schema_version(self, table_name: str = "", version: str = "") -> None:
        """Record the schema version stamp for the given table."""
        self.db_client.collection(self.versions_table_name).document(table_name).set(
            {"table_name": table_name, "version": version, "updated_at": int(time.time())}
        )

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from the database.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")
            runs_collection_ref = self._get_collection(table_type="runs", create_collection_if_not_found=False)
            # Firestore's 500-op-per-batch limit — chunk to survive cascade
            # deletes of sessions with many runs.
            batch = self.db_client.batch()
            in_batch = 0
            deleted_count = 0

            def _flush():
                nonlocal batch, in_batch
                if in_batch > 0:
                    batch.commit()
                    batch = self.db_client.batch()
                    in_batch = 0

            def _stage_delete(ref):
                nonlocal batch, in_batch
                batch.delete(ref)
                in_batch += 1
                if in_batch >= FIRESTORE_BATCH_LIMIT:
                    _flush()

            for session_id in session_ids:
                query = collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
                if user_id is not None:
                    query = query.where(filter=FieldFilter("user_id", "==", user_id))
                for doc in query.stream():
                    _stage_delete(doc.reference)
                    deleted_count += 1

                if runs_collection_ref is not None:
                    runs_query = runs_collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
                    if user_id is not None:
                        runs_query = runs_query.where(filter=FieldFilter("user_id", "==", user_id))
                    for run_doc in runs_query.stream():
                        _stage_delete(run_doc.reference)

            _flush()

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
        """Read a session from the database.

        Args:
            session_id (str): The ID of the session to get.
            session_type (Optional[SessionType]): The type of session to get. If None, the type is inferred.
            user_id (Optional[str]): The ID of the user to get the session for.
            deserialize (Optional[bool]): Whether to deserialize the session. Defaults to True.

        Returns:
            Union[Session, Dict[str, Any], None]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If there is an error reading the session.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")
            runs_collection_ref = self._get_collection(table_type="runs", create_collection_if_not_found=False)

            query = collection_ref.where(filter=FieldFilter("session_id", "==", session_id))

            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))

            docs = query.stream()
            result = None
            for doc in docs:
                result = doc.to_dict()
                break

            if result is None:
                return None

            session = deserialize_session_json_fields(result)

            # Attach runs from the runs collection, merged with any runs still
            # sitting in the legacy `runs` field.
            if runs_collection_ref is not None:
                runs_data = self._get_session_runs_docs(runs_collection_ref, session_id)
                session["runs"] = merge_runs_table_with_legacy_blob(runs_data, session.get("runs"))
            if runs_limit is not None:
                # No query engine to push "last N" down: filter+slice in memory to
                # match the SQL fast path (drop member/skip-status runs, then last N).
                session["runs"] = filter_context_runs(session.get("runs") or [])[-runs_limit:]

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Exception reading session: {str(e)}")
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
        """Get all sessions.

        Args:
            session_type (Optional[SessionType]): The type of session to get.
            user_id (Optional[str]): The ID of the user to get the session for.
            component_id (Optional[str]): The ID of the component to get the session for.
            session_name (Optional[str]): The name of the session to filter by.
            start_timestamp (Optional[int]): The start timestamp to filter sessions by.
            end_timestamp (Optional[int]): The end timestamp to filter sessions by.
            limit (Optional[int]): The limit of the sessions to get.
            page (Optional[int]): The page number to get.
            sort_by (Optional[str]): The field to sort the sessions by.
            sort_order (Optional[str]): The order to sort the sessions by.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.

        Returns:
            Union[List[AgentSession], List[TeamSession], List[WorkflowSession], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of Session objects
                - When deserialize=False: List of session dictionaries and the total count

        Raises:
            Exception: If there is an error reading the sessions.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")
            if collection_ref is None:
                return [] if deserialize else ([], 0)
            runs_collection_ref = self._get_collection(table_type="runs", create_collection_if_not_found=False)

            query = collection_ref

            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if session_type is not None:
                query = query.where(filter=FieldFilter("session_type", "==", session_type.value))
            if component_id is not None:
                if session_type == SessionType.AGENT:
                    query = query.where(filter=FieldFilter("agent_id", "==", component_id))
                elif session_type == SessionType.TEAM:
                    query = query.where(filter=FieldFilter("team_id", "==", component_id))
                elif session_type == SessionType.WORKFLOW:
                    query = query.where(filter=FieldFilter("workflow_id", "==", component_id))
            if start_timestamp is not None:
                query = query.where(filter=FieldFilter("created_at", ">=", start_timestamp))
            if end_timestamp is not None:
                query = query.where(filter=FieldFilter("created_at", "<=", end_timestamp))
            if session_name is not None:
                query = query.where(filter=FieldFilter("session_data.session_name", "==", session_name))

            # Apply sorting
            query = apply_sorting(query, sort_by, sort_order)

            # Get all documents for counting before pagination
            all_docs = query.stream()
            all_records = [doc.to_dict() for doc in all_docs]

            # Apply component_id filter in-memory when session_type is None
            # (Firestore doesn't support OR queries across different fields)
            if component_id is not None and session_type is None:
                all_records = [
                    r
                    for r in all_records
                    if r.get("agent_id") == component_id
                    or r.get("team_id") == component_id
                    or r.get("workflow_id") == component_id
                ]

            if not all_records:
                return [] if deserialize else ([], 0)

            all_sessions_raw = [deserialize_session_json_fields(record) for record in all_records]

            # Get total count before pagination
            total_count = len(all_sessions_raw)

            # Apply pagination to the results
            if limit is not None and page is not None:
                start_index = (page - 1) * limit
                end_index = start_index + limit
                sessions_raw = all_sessions_raw[start_index:end_index]
            elif limit is not None:
                sessions_raw = all_sessions_raw[:limit]
            else:
                sessions_raw = all_sessions_raw

            # Search scans skip the runs table; the record's legacy runs field is kept for merging later.
            # Attach runs from the runs collection, merged with any runs still
            # in the legacy `runs` field.
            if include_runs and runs_collection_ref is not None and sessions_raw:
                runs_by_session = self._get_sessions_runs_docs(
                    runs_collection_ref, [s["session_id"] for s in sessions_raw]
                )
                for s in sessions_raw:
                    runs_data = runs_by_session.get(s["session_id"], [])
                    s["runs"] = merge_runs_table_with_legacy_blob(runs_data, s.get("runs"))

            if not deserialize:
                return sessions_raw, total_count

            sessions = deserialize_sessions(session_type, sessions_raw)

            if not sessions:
                return []

            return sessions

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
        """Rename a session in the database.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name of the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to deserialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If there is an error renaming the session.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")

            query = collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if session_type is not None:
                query = query.where(filter=FieldFilter("session_type", "==", session_type.value))
            docs = query.stream()
            doc_ref = next((doc.reference for doc in docs), None)

            if doc_ref is None:
                return None

            # Check if session_data is stored as JSON string (legacy) or native map.
            # Legacy sessions stored session_data as a JSON string, but Firestore's dot notation
            # (e.g., "session_data.session_name") only works with native maps. Using dot notation
            # on a JSON string overwrites the entire field, causing data loss.
            # For legacy sessions, we use read-modify-write which also migrates them to native maps.
            current_doc = doc_ref.get()
            if not current_doc.exists:
                return None

            current_data = current_doc.to_dict()
            session_data = current_data.get("session_data") if current_data else None

            if session_data is None or isinstance(session_data, str):
                existing_session = self.get_session(session_id, session_type, user_id=user_id, deserialize=True)
                if existing_session is None:
                    return None
                existing_session = cast(Session, existing_session)
                if existing_session.session_data is None:
                    existing_session.session_data = {}
                existing_session.session_data["session_name"] = session_name
                return self.upsert_session(existing_session, deserialize=deserialize)

            # Native map format - use efficient dot notation update
            doc_ref.update({"session_data.session_name": session_name, "updated_at": int(time.time())})

            updated_doc = doc_ref.get()
            if not updated_doc.exists:
                return None

            result = updated_doc.to_dict()
            if result is None:
                return None
            deserialized_session = deserialize_session_json_fields(result)

            # Attach runs from the runs collection
            runs_collection_ref = self._get_collection(table_type="runs", create_collection_if_not_found=False)
            if runs_collection_ref is not None:
                runs_data = self._get_session_runs_docs(runs_collection_ref, session_id)
                deserialized_session["runs"] = merge_runs_table_with_legacy_blob(
                    runs_data, deserialized_session.get("runs")
                )

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

            if not deserialize:
                return deserialized_session

            return deserialize_session(session_type, deserialized_session)

        except Exception as e:
            log_error(f"Exception renaming session: {str(e)}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update a session in the database.

        Args:
            session (Session): The session to upsert.

        Returns:
            Optional[Session]: The upserted session.

        Raises:
            Exception: If there is an error upserting the session.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions", create_collection_if_not_found=True)

            session_dict = session.to_dict(include_runs=False)

            if isinstance(session, AgentSession):
                record = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.AGENT.value,
                    "agent_id": session_dict.get("agent_id"),
                    "user_id": session_dict.get("user_id"),
                    "agent_data": session_dict.get("agent_data"),
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }
            elif isinstance(session, TeamSession):
                record = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.TEAM.value,
                    "team_id": session_dict.get("team_id"),
                    "user_id": session_dict.get("user_id"),
                    "team_data": session_dict.get("team_data"),
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }
            elif isinstance(session, WorkflowSession):
                record = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.WORKFLOW.value,
                    "workflow_id": session_dict.get("workflow_id"),
                    "user_id": session_dict.get("user_id"),
                    "workflow_data": session_dict.get("workflow_data"),
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }
            else:
                raise ValueError(f"Invalid session type: {session.session_type}")

            # Find existing document or create new one
            docs = collection_ref.where(filter=FieldFilter("session_id", "==", record["session_id"])).stream()
            doc_ref = next((doc.reference for doc in docs), None)

            existing_data: Optional[Dict[str, Any]] = None
            if doc_ref is not None:
                existing_doc = doc_ref.get()
                if existing_doc.exists:
                    existing_data = existing_doc.to_dict() or {}
                    if existing_data.get("user_id") is not None and existing_data.get("user_id") != record.get(
                        "user_id"
                    ):
                        return None
            else:
                # Create new document
                doc_ref = collection_ref.document()
            reopen_session_ids = get_metrics_reopen_session_ids(
                [existing_data] if existing_data is not None else [], [record]
            )

            # The legacy `runs` field is intentionally left untouched: set(merge=True)
            # preserves it as a frozen backup until cleanup_legacy_runs_field() removes it.
            # Deleting it here would lose history for sessions not yet migrated.
            # The stored created_at, which keeps the session on the day it was created
            if existing_data and existing_data.get("created_at") is not None:
                record["created_at"] = existing_data["created_at"]
            doc_ref.set(record, merge=True)

            # Runs are persisted separately via upsert_run by the caller (agent loop).
            # Get the updated document
            updated_doc = doc_ref.get()
            if not updated_doc.exists:
                return None

            result = updated_doc.to_dict()
            if result is None:
                return None
            if result.get("session_id") in reopen_session_ids:
                self._reopen_metrics_days([result.get("created_at")])
            deserialized_session = deserialize_session_json_fields(result)

            # Attach the in-memory runs to the returned dict so callers see the full picture
            deserialized_session["runs"] = [
                run if isinstance(run, dict) else run.to_dict() for run in session.runs or []
            ]

            if not deserialize:
                return deserialized_session

            if isinstance(session, AgentSession):
                return AgentSession.from_dict(deserialized_session)
            elif isinstance(session, TeamSession):
                return TeamSession.from_dict(deserialized_session)
            else:
                return WorkflowSession.from_dict(deserialized_session)

        except Exception as e:
            log_error(f"Exception upserting session: {str(e)}")
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
                f"FirestoreDb doesn't support efficient bulk operations, falling back to individual upserts for {len(sessions)} sessions"
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
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Raises:
            Exception: If there is an error deleting the memory.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")

            # If user_id is provided, verify the memory belongs to the user before deleting
            if user_id is not None:
                docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()
                for doc in docs:
                    data = doc.to_dict()
                    if data.get("user_id") != user_id:
                        log_debug(f"Memory {memory_id} does not belong to user {user_id}")
                        return
                    doc.reference.delete()
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                    return
            else:
                docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()
                deleted_count = 0
                for doc in docs:
                    doc.reference.delete()
                    deleted_count += 1

                success = deleted_count > 0
                if success:
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                else:
                    log_debug(f"No user memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting user memory: {str(e)}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Raises:
            Exception: If there is an error deleting the memories.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")
            # Chunk to the Firestore 500-op-per-batch limit.
            batch = self.db_client.batch()
            in_batch = 0
            deleted_count = 0

            def _stage(ref):
                nonlocal batch, in_batch, deleted_count
                batch.delete(ref)
                in_batch += 1
                deleted_count += 1
                if in_batch >= FIRESTORE_BATCH_LIMIT:
                    batch.commit()
                    batch = self.db_client.batch()
                    in_batch = 0

            if user_id is not None:
                for memory_id in memory_ids:
                    docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()
                    for doc in docs:
                        data = doc.to_dict()
                        if data.get("user_id") == user_id:
                            _stage(doc.reference)
            else:
                for memory_id in memory_ids:
                    docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()
                    for doc in docs:
                        _stage(doc.reference)

            if in_batch > 0:
                batch.commit()

            if deleted_count == 0:
                log_info(f"No memories found with ids: {memory_ids}")
            else:
                log_info(f"Successfully deleted {deleted_count} memories")

        except Exception as e:
            log_error(f"Error deleting memories: {str(e)}")
            raise e

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            List[str]: The topics.

        Raises:
            Exception: If there is an error getting the topics.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")
            if collection_ref is None:
                return []

            query = (
                collection_ref
                if user_id is None
                else collection_ref.where(filter=FieldFilter("user_id", "==", user_id))
            )
            docs = query.stream()

            all_topics: set[str] = set()
            for doc in docs:
                data = doc.to_dict()
                topics = data.get("topics", [])
                if topics and isinstance(topics, list):
                    all_topics.update(topics)

            return [topic for topic in all_topics if topic]

        except Exception as e:
            log_error(f"Exception getting all memory topics: {str(e)}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[UserMemory]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Returns:
            Optional[UserMemory]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If there is an error getting the memory.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")
            docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()

            result = None
            for doc in docs:
                result = doc.to_dict()
                break

            if result is None:
                return None

            # Filter by user_id if provided
            if user_id and result.get("user_id") != user_id:
                return None

            if not deserialize:
                return result

            return UserMemory.from_dict(result)

        except Exception as e:
            log_error(f"Exception getting user memory: {str(e)}")
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
        """Get all memories from the database as UserMemory objects.

        Args:
            user_id (Optional[str]): The ID of the user to get the memories for.
            agent_id (Optional[str]): The ID of the agent to get the memories for.
            team_id (Optional[str]): The ID of the team to get the memories for.
            topics (Optional[List[str]]): The topics to filter the memories by.
            search_content (Optional[str]): The content to filter the memories by.
            limit (Optional[int]): The limit of the memories to get.
            page (Optional[int]): The page number to get.
            sort_by (Optional[str]): The field to sort the memories by.
            sort_order (Optional[str]): The order to sort the memories by.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the memories and the total count.

        Raises:
            Exception: If there is an error getting the memories.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")
            if collection_ref is None:
                return [] if deserialize else ([], 0)

            query = collection_ref

            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id is not None:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id is not None:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if topics is not None and len(topics) > 0:
                query = query.where(filter=FieldFilter("topics", "array_contains_any", topics))
            if search_content is not None:
                query = query.where(filter=FieldFilter("memory", "==", search_content))

            # Apply sorting
            query = apply_sorting(query, sort_by, sort_order)

            # Get all documents
            docs = query.stream()
            all_records = [doc.to_dict() for doc in docs]

            total_count = len(all_records)

            # Apply pagination to the filtered results
            if limit is not None and page is not None:
                start_index = (page - 1) * limit
                end_index = start_index + limit
                records = all_records[start_index:end_index]
            elif limit is not None:
                records = all_records[:limit]
            else:
                records = all_records
            if not deserialize:
                return records, total_count

            return [UserMemory.from_dict(record) for record in records]

        except Exception as e:
            log_error(f"Exception getting user memories: {str(e)}")
            raise e

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memories stats.

        Args:
            limit (Optional[int]): The limit of the memories to get.
            page (Optional[int]): The page number to get.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the memories stats and the total count.

        Raises:
            Exception: If there is an error getting the memories stats.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")

            if user_id is not None:
                query = collection_ref.where(filter=FieldFilter("user_id", "==", user_id))
            else:
                query = collection_ref.where(filter=FieldFilter("user_id", "!=", None))

            docs = query.stream()

            user_stats = {}
            for doc in docs:
                data = doc.to_dict()
                current_user_id = data.get("user_id")
                if current_user_id:
                    if current_user_id not in user_stats:
                        user_stats[current_user_id] = {
                            "user_id": current_user_id,
                            "total_memories": 0,
                            "last_memory_updated_at": 0,
                        }
                    user_stats[current_user_id]["total_memories"] += 1
                    updated_at = data.get("updated_at", 0)
                    if updated_at > user_stats[current_user_id]["last_memory_updated_at"]:
                        user_stats[current_user_id]["last_memory_updated_at"] = updated_at

            # Convert to list and sort
            formatted_results = list(user_stats.values())
            formatted_results.sort(key=lambda x: x["last_memory_updated_at"], reverse=True)

            total_count = len(formatted_results)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                formatted_results = formatted_results[start_idx : start_idx + limit]

            return formatted_results, total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {str(e)}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in the database.

        Args:
            memory (UserMemory): The memory to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If there is an error upserting the memory.
        """
        try:
            collection_ref = self._get_collection(table_type="memories", create_collection_if_not_found=True)
            if collection_ref is None:
                return None

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            update_doc = memory.to_dict()
            update_doc["updated_at"] = int(time.time())

            # Find existing document or create new one
            docs = collection_ref.where("memory_id", "==", memory.memory_id).stream()
            doc_ref = next((doc.reference for doc in docs), None)

            if doc_ref is None:
                doc_ref = collection_ref.document()

            doc_ref.set(update_doc, merge=True)

            if not deserialize:
                return update_doc

            return UserMemory.from_dict(update_doc)

        except Exception as e:
            log_error(f"Exception upserting user memory: {str(e)}")
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
                f"FirestoreDb doesn't support efficient bulk operations, falling back to individual upserts for {len(memories)} memories"
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
            collection_ref = self._get_collection(table_type="memories")

            # Get all documents in the collection
            docs = collection_ref.stream()

            # Delete all documents in batches
            batch = self.db_client.batch()
            batch_count = 0

            for doc in docs:
                batch.delete(doc.reference)
                batch_count += 1

                # Firestore batch has a limit of 500 operations
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db_client.batch()
                    batch_count = 0

            # Commit remaining operations
            if batch_count > 0:
                batch.commit()

        except Exception as e:
            log_error(f"Exception deleting all memories: {str(e)}")
            raise e

    # -- Metrics methods --
    def _reopen_metrics_days(self, created_ats: Sequence[Optional[int]]) -> None:
        """Reopen the metrics of each day a write changed, right after the write, so the next calculation rebuilds
        it. A day it could not reopen is retried by the next write.

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
            # Looked up only when a day reopens. None when no day was calculated yet: a collection exists only while
            # it holds a document
            aggregate_metrics_collection_ref = getattr(self, "aggregate_metrics_collection", None)
            if aggregate_metrics_collection_ref is None:
                if not list(self.db_client.collection(self.aggregate_metrics_table_name).limit(1).stream()):
                    self._metrics_days_not_reopened.clear()
                    return
                aggregate_metrics_collection_ref = self._get_collection(table_type="aggregate_metrics")
            for day in days:
                reopen_metrics_day(aggregate_metrics_collection_ref, day)
            self._metrics_days_not_reopened.difference_update(days)
        except Exception as e:
            self._metrics_days_not_reopened.update(days)
            log_warning(
                f"Could not reopen the metrics of {', '.join(str(day) for day in days)}: {database_error_message(e)}"
            )

    def _get_metrics_refresh_row(self, refreshes_collection_ref) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get the document of the metrics refreshes collection, and the locked_at at or before which its lock is
        stale, by the process clock."""
        stale_lock_threshold = int(time.time()) - METRICS_LOCK_SECONDS
        snapshot = refreshes_collection_ref.document(METRICS_REFRESH_ID).get()
        if not snapshot.exists:
            # Before the first refresh there is no lock to judge stale
            return None, 0
        return deserialize_metrics_refresh_row(snapshot.to_dict()), stale_lock_threshold

    def _claim_metrics_refresh(self, refreshes_collection_ref, worker_id: str) -> Optional[Dict[str, Any]]:
        """Claim the document of the metrics refreshes collection, so one process calculates metrics at a time.

        Args:
            refreshes_collection_ref: The metrics refreshes collection.
            worker_id (str): The id of this calculation, which heartbeats and releases the claim.

        Returns:
            Optional[Dict[str, Any]]: The claimed document, with when the last calculation finished and its
                fingerprint. None when another process holds it.
        """
        refresh_ref = refreshes_collection_ref.document(METRICS_REFRESH_ID)

        @transactional
        def _claim(transaction) -> Optional[Dict[str, Any]]:
            # Read and written in one transaction, so two processes never both find the document free
            snapshot = refresh_ref.get(transaction=transaction)
            refresh_row = deserialize_metrics_refresh_row(snapshot.to_dict() if snapshot.exists else {})
            now = int(time.time())
            # A stale lock is taken over: the process that held it stopped
            if refresh_row["locked_by"] is not None and refresh_row["locked_at"] > now - METRICS_LOCK_SECONDS:
                return None
            refresh_row.update(
                id=METRICS_REFRESH_ID, locked_by=worker_id, locked_at=now, started_at=now, status="running", error=None
            )
            transaction.set(refresh_ref, refresh_row)
            return refresh_row

        return _claim(self.db_client.transaction())

    def _heartbeat_metrics_refresh(self, transaction, refreshes_collection_ref, worker_id: str) -> bool:
        """Refresh locked_at for this worker's metrics refresh. False when another process took it over."""
        refresh_ref = refreshes_collection_ref.document(METRICS_REFRESH_ID)
        snapshot = refresh_ref.get(transaction=transaction)
        if not snapshot.exists or (snapshot.to_dict() or {}).get("locked_by") != worker_id:
            return False
        transaction.update(refresh_ref, {"locked_at": int(time.time())})
        return True

    def _mark_metrics_refresh_rebuild(self, refreshes_collection_ref) -> bool:
        """Write a mark no fingerprint equals on the document of the metrics refreshes collection, so the next
        calculation rebuilds yesterday and today. False when a transaction kept the document locked through every try."""
        for _ in range(3):
            try:
                refreshes_collection_ref.document(METRICS_REFRESH_ID).update({"fingerprint": ["rebuild", uuid4().hex]})
                return True
            except NotFound:
                # Before the first refresh there is no document to mark
                return True
            except Aborted:
                # A transaction reading the document holds its lock until it commits
                continue
        return False

    def _release_metrics_refresh(
        self,
        refreshes_collection_ref,
        worker_id: Optional[str],
        error: Optional[str] = None,
        fingerprint: Optional[List[Any]] = None,
        stopped: bool = False,
        claimed_fingerprint: Optional[List[Any]] = None,
    ) -> None:
        """Release the document of the metrics refreshes collection: completed, with the fingerprint, without an
        error, failed with one, and as the last completed refresh left it when the calculation stopped.

        Args:
            refreshes_collection_ref: The metrics refreshes collection.
            worker_id (Optional[str]): The id of the calculation that claimed the document. None writes the document
                only while no process holds it, and creates it before any refresh.
            error (Optional[str]): The error the calculation failed with. None when it completed.
            fingerprint (Optional[List[Any]]): The fingerprint of yesterday and today, stored once it completed.
            stopped (bool): Whether the calculation stopped before it finished.
            claimed_fingerprint (Optional[List[Any]]): The fingerprint of the claimed document. A rebuild that marked
                another one since keeps its mark.
        """
        refresh_ref = refreshes_collection_ref.document(METRICS_REFRESH_ID)

        @transactional
        def _release(transaction) -> None:
            snapshot = refresh_ref.get(transaction=transaction)
            refresh_row = (snapshot.to_dict() or {}) if snapshot.exists else {}
            if refresh_row.get("locked_by") != worker_id:
                return
            if not snapshot.exists:
                # Before any refresh there is no document to update
                created_row = deserialize_metrics_refresh_row({})
                created_row.update(id=METRICS_REFRESH_ID, started_at=int(time.time()), status="failed", error=error)
                transaction.set(refresh_ref, created_row)
                return
            values: Dict[str, Any] = {"locked_by": None, "locked_at": None}
            if stopped:
                # The days it did not reach stay open for the next calculation; a first one that stopped has none to
                # show
                if refresh_row.get("finished_at") is not None:
                    values.update(status="completed", error=None)
                else:
                    values.update(status="failed", error=METRICS_STOPPED_ERROR)
            elif error is None:
                values.update(status="completed", error=None, finished_at=int(time.time()), fingerprint=fingerprint)
                if refresh_row.get("fingerprint") != claimed_fingerprint:
                    # A rebuild that marked the fingerprint after the claim keeps its mark, so the next calculation
                    # rebuilds yesterday and today
                    values["fingerprint"] = refresh_row.get("fingerprint")
            else:
                values.update(status="failed", error=error)
            transaction.update(refresh_ref, values)

        try:
            _release(self.db_client.transaction())
        except Exception as e:
            log_debug(f"Error releasing metrics refresh: {e}")

    def _get_metrics_fingerprint(
        self, sessions_collection_ref, runs_collection_ref, yesterday: date
    ) -> Optional[List[Any]]:
        """Get the count and update times of the sessions and runs of yesterday and today. None while one of them was
        updated in the current second, which a second update in that same second would leave unchanged, and when
        Firestore cannot count them."""
        start_timestamp = int(datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        current_time = int(time.time())
        fingerprint: List[Any] = [yesterday.isoformat()]
        try:
            for collection_ref in [sessions_collection_ref, runs_collection_ref]:
                if collection_ref is None:
                    continue
                # Counted from the index, so a check reads no document
                aggregation = (
                    collection_ref.where(filter=FieldFilter("created_at", ">=", start_timestamp))
                    .count(alias="count")
                    .sum("updated_at", alias="total_updated_at")
                    .get()
                )
                values = {result.alias: result.value for result in aggregation[0]}
                # Firestore keeps no maximum, so a write of the current second is looked up, whatever day it is of
                recent_docs = (
                    collection_ref.where(filter=FieldFilter("updated_at", ">=", current_time))
                    .limit(1)
                    .select(["updated_at"])
                    .stream()
                )
                if list(recent_docs):
                    return None
                fingerprint.extend([int(values["count"]), int(values["total_updated_at"] or 0)])
        except FailedPrecondition:
            log_warning("The index of the metrics fingerprint is not built yet; yesterday and today are rebuilt")
            return None
        return fingerprint

    def _get_metrics_data_days(self, collection_ref, today: date, starting_date: Optional[date] = None) -> Set[date]:
        """Get every day up to today, from starting_date on, with a document of the given sessions or runs collection.

        Each day found is one query for the first document after it, so a first calculation never reads every
        document.
        """
        days: Set[date] = set()
        query = collection_ref
        if starting_date is not None:
            starting_timestamp = int(
                datetime.combine(starting_date, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
            )
            query = collection_ref.where(filter=FieldFilter("created_at", ">=", starting_timestamp))
        while True:
            docs = list(query.order_by("created_at").limit(1).select(["created_at"]).stream())
            if not docs:
                return days
            day = datetime.fromtimestamp(docs[0].to_dict()["created_at"], tz=timezone.utc).date()
            if day > today:
                return days
            days.add(day)
            next_day_timestamp = int(
                datetime.combine(day + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
            )
            query = collection_ref.where(filter=FieldFilter("created_at", ">=", next_day_timestamp))

    def _get_metrics_dates_to_calculate(
        self,
        aggregate_metrics_collection_ref,
        sessions_collection_ref,
        runs_collection_ref,
        refresh_row: Dict[str, Any],
        rebuild_from: Optional[date] = None,
    ) -> Tuple[List[date], Optional[List[Any]]]:
        """Get the days whose metrics a calculation rebuilds, and the fingerprint of yesterday and today.

        Args:
            aggregate_metrics_collection_ref: The aggregate metrics collection.
            sessions_collection_ref: The sessions collection.
            runs_collection_ref: The runs collection.
            refresh_row (Dict[str, Any]): The document of the metrics refreshes collection, from
                _claim_metrics_refresh.
            rebuild_from (Optional[date]): The first day of a rebuild.

        Returns:
            Tuple[List[date], Optional[List[Any]]]: The days, oldest first, and the fingerprint to keep on the
                document of the metrics refreshes collection.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        dates_to_process: Set[date] = set()
        fingerprint = self._get_metrics_fingerprint(sessions_collection_ref, runs_collection_ref, yesterday)
        first_calculation = refresh_row["finished_at"] is None
        # Yesterday and today, when their sessions or runs changed since the last calculation
        if first_calculation or fingerprint is None or fingerprint != refresh_row["fingerprint"]:
            dates_to_process.update([yesterday, today])

        # Every earlier day still open: not yet completed, or reopened by a write since
        open_docs = (
            aggregate_metrics_collection_ref.where(filter=FieldFilter("aggregation_period", "==", "daily"))
            .where(filter=FieldFilter("user_id", "==", ""))
            .where(filter=FieldFilter("completed", "==", False))
            .where(filter=FieldFilter("date", "<", yesterday.isoformat()))
            .select(["date"])
            .stream()
        )
        dates_to_process.update(deserialize_metrics_row(doc.to_dict())["date"] for doc in open_docs)
        # Every earlier day from the day before the last calculation finished, whose writes reopened nothing while
        # it was yesterday or today
        if not first_calculation:
            dates_to_process.update(metrics_days_since_last_calculation(refresh_row["finished_at"], yesterday))

        # Until a first calculation has finished, every day with a session or a run not yet completed; with
        # rebuild_from, every day with one from that date on
        if first_calculation or rebuild_from is not None:
            completed_days: Set[date] = set()
            if first_calculation:
                completed_docs = (
                    aggregate_metrics_collection_ref.where(filter=FieldFilter("aggregation_period", "==", "daily"))
                    .where(filter=FieldFilter("user_id", "==", ""))
                    .where(filter=FieldFilter("completed", "==", True))
                    .select(["date"])
                    .stream()
                )
                completed_days = {deserialize_metrics_row(doc.to_dict())["date"] for doc in completed_docs}
            # Only days with data, so one session dated long ago never builds every empty day since
            for collection_ref in [sessions_collection_ref, runs_collection_ref]:
                if collection_ref is None:
                    continue
                for data_date in self._get_metrics_data_days(
                    collection_ref, today, rebuild_from if not first_calculation else None
                ):
                    # A rebuild takes every day with data from its first day, completed or not
                    rebuilt = rebuild_from is not None and data_date >= rebuild_from
                    if rebuilt or (first_calculation and data_date not in completed_days):
                        dates_to_process.add(data_date)

        return sorted(dates_to_process), fingerprint

    def _get_open_metrics_months(self, aggregate_metrics_collection_ref) -> List[date]:
        """Get the first day of every month before the current one whose month row is still open: not completed yet,
        or reopened by a day a calculation rebuilt before it stopped."""
        current_month = datetime.now(timezone.utc).date().replace(day=1)
        docs = (
            aggregate_metrics_collection_ref.where(filter=FieldFilter("aggregation_period", "==", "monthly"))
            .where(filter=FieldFilter("user_id", "==", ""))
            .where(filter=FieldFilter("completed", "==", False))
            .where(filter=FieldFilter("date", "<", current_month.isoformat()))
            .select(["date"])
            .stream()
        )
        return [deserialize_metrics_row(doc.to_dict())["date"] for doc in docs]

    def _get_metrics_legacy_runs(
        self,
        sessions_collection_ref,
        runs_collection_ref,
        start_timestamp: int,
        end_timestamp: int,
    ) -> Tuple[Dict[date, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
        """Get the runs not yet migrated out of the sessions' legacy runs field, created in the given time range.

        Args:
            sessions_collection_ref: The sessions collection.
            runs_collection_ref: The runs collection. A run it also holds is read from there.
            start_timestamp (int): The start of the range, included.
            end_timestamp (int): The end of the range, not included.

        Returns:
            Tuple[Dict[date, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]: The legacy runs by the UTC day they
                were created on, and by their id.
        """
        # A session holds runs created after it started and before it was last written
        legacy_sessions_query = sessions_collection_ref.where(
            filter=FieldFilter("updated_at", ">=", start_timestamp)
        ).select(["session_id", "user_id", "created_at", "runs"])
        legacy_sessions = [
            session
            for session in (doc.to_dict() for doc in legacy_sessions_query.stream())
            if session.get("runs") and (session.get("created_at") or 0) < end_timestamp
        ]
        legacy_runs = [
            legacy_run
            for legacy_run in get_metrics_legacy_runs(legacy_sessions)
            if start_timestamp <= (legacy_run["created_at"] or 0) < end_timestamp
        ]
        # The runs collection wins on a run in both, as merge_runs_table_with_legacy_blob does
        migrated_run_ids: Set[str] = set()
        if runs_collection_ref is not None:
            legacy_run_ids = [legacy_run["run_id"] for legacy_run in legacy_runs]
            for start in range(0, len(legacy_run_ids), METRICS_IN_LIST_LIMIT):
                migrated_query = runs_collection_ref.where(
                    filter=FieldFilter("run_id", "in", legacy_run_ids[start : start + METRICS_IN_LIST_LIMIT])
                ).select(["run_id"])
                migrated_run_ids.update(doc.to_dict()["run_id"] for doc in migrated_query.stream())
        legacy_runs_by_day: Dict[date, List[Dict[str, Any]]] = {}
        legacy_runs_by_id: Dict[str, Dict[str, Any]] = {}
        for legacy_run in legacy_runs:
            if legacy_run["run_id"] in migrated_run_ids:
                continue
            legacy_run_day = datetime.fromtimestamp(legacy_run["created_at"], tz=timezone.utc).date()
            legacy_runs_by_day.setdefault(legacy_run_day, []).append(legacy_run)
            legacy_runs_by_id[legacy_run["run_id"]] = legacy_run
        return legacy_runs_by_day, legacy_runs_by_id

    def _get_metrics_parent_runs(self, runs_collection_ref, parent_run_ids: List[str]) -> List[Dict[str, Any]]:
        """Get the stored runs that started the given runs, and the runs that started those, up to the whole run."""
        parent_runs: List[Dict[str, Any]] = []
        seen_run_ids: Set[str] = set()
        while parent_run_ids:
            seen_run_ids.update(parent_run_ids)
            for start in range(0, len(parent_run_ids), METRICS_IN_LIST_LIMIT):
                parents_query = runs_collection_ref.where(
                    filter=FieldFilter("run_id", "in", parent_run_ids[start : start + METRICS_IN_LIST_LIMIT])
                ).select(
                    [
                        "run_id",
                        "run_type",
                        "agent_id",
                        "team_id",
                        "workflow_id",
                        "parent_run_id",
                    ]
                )
                parent_runs.extend(doc.to_dict() for doc in parents_query.stream())
            parent_run_ids = sorted(
                {run["parent_run_id"] for run in parent_runs if run.get("parent_run_id")} - seen_run_ids
            )
        return parent_runs

    def _write_aggregate_metrics_rows(
        self,
        aggregate_metrics_collection_ref,
        aggregate_metrics_rows: List[Dict[str, Any]],
        rows_changed: bool,
        read_version: Optional[int],
        refreshes_collection_ref,
        worker_id: str,
        row_writes: Sequence[Tuple[Any, Optional[Dict[str, Any]]]] = (),
    ) -> bool:
        """Write a period's rows: the given component metrics writes, then the user rows of the aggregate metrics
        collection, then the everyone row, from build_aggregate_metrics_rows. False when another process took the
        refresh over.

        Firestore commits 500 writes at most at once, so the refresh is heartbeated in each commit, and the
        everyone row is written last, in a transaction that heartbeats it: it is completed only while it still has the
        version read before the period's rows.

        Args:
            aggregate_metrics_collection_ref: The aggregate metrics collection.
            aggregate_metrics_rows (List[Dict[str, Any]]): The period's rows, the everyone row first.
            rows_changed (bool): Whether a component metrics row of the period was written or deleted.
            read_version (Optional[int]): The version of the everyone row read before the period's rows were rebuilt.
            refreshes_collection_ref: The metrics refreshes collection.
            worker_id (str): The id of this calculation, which holds the refresh.
            row_writes (Sequence[Tuple[Any, Optional[Dict[str, Any]]]]): The component metrics documents to write
                first, each with its data, or None to delete it.
        """
        period, period_date = aggregate_metrics_rows[0]["aggregation_period"], aggregate_metrics_rows[0]["date"]
        stored_docs = (
            aggregate_metrics_collection_ref.where(filter=FieldFilter("aggregation_period", "==", period))
            .where(filter=FieldFilter("date", "==", period_date.isoformat()))
            .stream()
        )
        stored_by_user = {
            row["user_id"]: row for row in (deserialize_metrics_row(doc.to_dict()) for doc in stored_docs)
        }
        everyone_row, changed_rows, stale_user_ids = aggregate_metrics_rows_to_write(
            aggregate_metrics_rows, list(stored_by_user.values()), rows_changed
        )
        writes = list(row_writes)
        writes.extend(
            (aggregate_metrics_collection_ref.document(aggregate_metrics_record_id(period, period_date, user_id)), None)
            for user_id in stale_user_ids
        )
        writes.extend(
            (
                aggregate_metrics_collection_ref.document(
                    aggregate_metrics_record_id(period, period_date, row["user_id"])
                ),
                serialize_metrics_row(aggregate_metrics_row_to_store(row, stored_by_user.get(row["user_id"]), None)),
            )
            for row in changed_rows
        )

        everyone_ref = aggregate_metrics_collection_ref.document(aggregate_metrics_record_id(period, period_date, ""))
        expected_version = read_version
        # Rows of more than one commit move the everyone row's version in the first, so a commit that fails later never
        # leaves them under the version read before them; rows of one commit keep it until the everyone row's write
        if len(writes) >= FIRESTORE_BATCH_LIMIT - 1 and "" in stored_by_user:
            writes.insert(0, (everyone_ref, {"version": Increment(1)}))
            expected_version = read_version + 1 if read_version is not None else None

        @transactional
        def _write_rows(transaction, rows) -> bool:
            # Heartbeated in the transaction of the rows, so a process whose lock went stale never writes them
            if not self._heartbeat_metrics_refresh(transaction, refreshes_collection_ref, worker_id):
                return False
            for doc_ref, data in rows:
                if data is None:
                    transaction.delete(doc_ref)
                elif doc_ref is everyone_ref:
                    transaction.update(doc_ref, data)
                else:
                    transaction.set(doc_ref, data)
            return True

        # One write of each transaction is the heartbeat
        for start in range(0, len(writes), FIRESTORE_BATCH_LIMIT - 1):
            if not _write_rows(self.db_client.transaction(), writes[start : start + FIRESTORE_BATCH_LIMIT - 1]):
                return False

        @transactional
        def _write_everyone_row(transaction) -> bool:
            snapshot = everyone_ref.get(transaction=transaction)
            # Heartbeated in the transaction of the row, so a process whose lock went stale never overwrites the row of
            # the process that took the refresh over
            if not self._heartbeat_metrics_refresh(transaction, refreshes_collection_ref, worker_id):
                return False
            if everyone_row is not None:
                stored_row = deserialize_metrics_row(snapshot.to_dict()) if snapshot.exists else None
                transaction.set(
                    everyone_ref,
                    serialize_metrics_row(aggregate_metrics_row_to_store(everyone_row, stored_row, expected_version)),
                )
            return True

        # Written last, and completed only while its version is still the one the rows were written under, so a reopen
        # written since keeps the period open
        return _write_everyone_row(self.db_client.transaction())

    def _calculate_date_metrics(
        self,
        collection_ref,
        aggregate_metrics_collection_ref,
        sessions_collection_ref,
        runs_collection_ref,
        date_to_process: date,
        legacy_runs: List[Dict[str, Any]],
        legacy_runs_by_id: Dict[str, Dict[str, Any]],
        refreshes_collection_ref,
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
        everyone_doc = aggregate_metrics_collection_ref.document(
            aggregate_metrics_record_id("daily", date_to_process, "")
        ).get()
        read_version = (everyone_doc.to_dict() or {}).get("version") if everyone_doc.exists else None

        sessions_query = (
            sessions_collection_ref.where(filter=FieldFilter("created_at", ">=", start_timestamp))
            .where(filter=FieldFilter("created_at", "<", end_timestamp))
            .select(
                [
                    "session_id",
                    "session_type",
                    "user_id",
                    "agent_id",
                    "team_id",
                    "workflow_id",
                    "metadata",
                    "session_data.compaction_metrics",
                ]
            )
        )
        sessions = [doc.to_dict() for doc in sessions_query.stream()]
        for session in sessions:
            # A manual compaction's usage, which no run carries, is kept in the session's data
            session["compaction_metrics"] = (session.get("session_data") or {}).get("compaction_metrics")

        runs: List[Dict[str, Any]] = []
        if runs_collection_ref is not None:
            # Only the fields component metrics count. Firestore projects no deeper than a field, so the messages, the
            # tool calls and the nested runs are read whole
            runs_query = (
                runs_collection_ref.where(filter=FieldFilter("created_at", ">=", start_timestamp))
                .where(filter=FieldFilter("created_at", "<", end_timestamp))
                .select(
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
                        "run_data.metrics",
                        "run_data.model",
                        "run_data.model_provider",
                        "run_data.messages",
                        "run_data.tools",
                        "run_data.forked_from_message_index",
                        "run_data.forked_from_session_id",
                        "run_data.step_executor_runs",
                        "run_data.member_responses",
                        "run_data.workflow_agent_run",
                    ]
                )
            )
            run_docs = runs_query.stream()
            while True:
                batch = list(islice(run_docs, METRICS_BATCH_SIZE))
                if not batch:
                    break
                runs.extend(doc.to_dict() for doc in batch)
                # Checked between batches too, so a stop never waits for the whole of a large day
                if should_stop is not None and should_stop():
                    return False

        # A legacy run migrated to the runs collection since the legacy runs were read is among the day's runs, and
        # is counted from there
        day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
        runs.extend(run for run in legacy_runs if run["run_id"] not in day_run_ids)

        stored_run_ids: Set[str] = set()
        run_ids = sorted(metrics_nested_run_ids(runs))
        if runs_collection_ref is not None:
            # A nested run also stored as a run of its own is counted from that row, whatever day it is on
            for start in range(0, len(run_ids), METRICS_IN_LIST_LIMIT):
                stored_query = runs_collection_ref.where(
                    filter=FieldFilter("run_id", "in", run_ids[start : start + METRICS_IN_LIST_LIMIT])
                ).select(["run_id"])
                stored_run_ids.update(doc.to_dict()["run_id"] for doc in stored_query.stream())
        # A nested run also stored in a legacy runs field of the rebuild, as a team stored its members' runs, is
        # counted from that run
        stored_run_ids.update(run_id for run_id in run_ids if run_id in legacy_runs_by_id)

        # A run started by a run of another day, such as a member run after midnight, names that run's agent, team or
        # workflow as its parent, read from the legacy runs of the rebuild or the runs collection
        day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
        parent_run_ids = sorted({run["parent_run_id"] for run in runs if run.get("parent_run_id")} - day_run_ids)
        parent_runs = [legacy_runs_by_id[run_id] for run_id in parent_run_ids if run_id in legacy_runs_by_id]
        parent_run_ids = [run_id for run_id in parent_run_ids if run_id not in legacy_runs_by_id]
        if runs_collection_ref is not None:
            # A remote member's run after midnight is named by its team's run of the day before
            team_session_ids = sorted(metrics_remote_member_team_session_ids(runs))
            for start in range(0, len(team_session_ids), METRICS_IN_LIST_LIMIT):
                team_runs_query = (
                    runs_collection_ref.where(
                        filter=FieldFilter("session_id", "in", team_session_ids[start : start + METRICS_IN_LIST_LIMIT])
                    )
                    .where(filter=FieldFilter("created_at", ">=", start_timestamp - 86400))
                    .where(filter=FieldFilter("created_at", "<", start_timestamp))
                    .select(
                        [
                            "run_id",
                            "session_id",
                            "run_type",
                            "agent_id",
                            "team_id",
                            "workflow_id",
                            "parent_run_id",
                            "run_data.step_executor_runs",
                            "run_data.member_responses",
                            "run_data.workflow_agent_run",
                        ]
                    )
                )
                team_runs = [doc.to_dict() for doc in team_runs_query.stream()]
                parent_runs.extend(team_runs)
                parent_run_ids.extend(run["parent_run_id"] for run in team_runs if run.get("parent_run_id"))
            parent_runs.extend(self._get_metrics_parent_runs(runs_collection_ref, parent_run_ids))

        records = calculate_date_component_metrics(date_to_process, sessions, runs, stored_run_ids, parent_runs)
        stored_docs = (
            collection_ref.where(filter=FieldFilter("aggregation_period", "==", "daily"))
            .where(filter=FieldFilter("date", "==", date_to_process.isoformat()))
            .stream()
        )
        stored_rows_by_id = {doc.id: deserialize_metrics_row(doc.to_dict()) for doc in stored_docs}

        changed_rows, stale_keys = component_metrics_rows_to_write(records, list(stored_rows_by_id.values()))
        stored_ids_by_key = {
            (
                row["user_id"],
                row["component_type"],
                row["component_id"],
                row["parent_component_id"],
                row["root_component_id"],
            ): doc_id
            for doc_id, row in stored_rows_by_id.items()
        }
        row_writes: List[Tuple[Any, Optional[Dict[str, Any]]]] = [
            (collection_ref.document(stored_ids_by_key[key]), None) for key in stale_keys
        ]
        for row in changed_rows:
            doc_id = component_metrics_record_id(row)
            stored_row = stored_rows_by_id.get(doc_id)
            # A stored row keeps when it was created
            if stored_row is not None:
                row = {**row, "created_at": stored_row["created_at"]}
            row_writes.append((collection_ref.document(doc_id), serialize_metrics_row(row)))

        if not self._write_aggregate_metrics_rows(
            aggregate_metrics_collection_ref,
            build_aggregate_metrics_rows(records, "daily", date_to_process, metrics_day_completed(date_to_process)),
            rows_changed=bool(changed_rows or stale_keys),
            read_version=read_version,
            refreshes_collection_ref=refreshes_collection_ref,
            worker_id=worker_id,
            row_writes=row_writes,
        ):
            return False
        if changed_rows or stale_keys:
            # Reopened with the day, so a calculation that stops before its months leaves the month for the next
            reopen_metrics_month(aggregate_metrics_collection_ref, date_to_process.replace(day=1))
        return True

    def _calculate_month_metrics(
        self,
        collection_ref,
        aggregate_metrics_collection_ref,
        month_start: date,
        refreshes_collection_ref,
        worker_id: str,
    ) -> bool:
        """Rebuild the month rows of the aggregate metrics collection from the component metrics rows of the month's
        days. False when another process took the refresh over."""
        everyone_doc = aggregate_metrics_collection_ref.document(
            aggregate_metrics_record_id("monthly", month_start, "")
        ).get()
        read_version = (everyone_doc.to_dict() or {}).get("version") if everyone_doc.exists else None
        # Streamed, so a month of many rows is added up a batch at a time instead of held whole
        docs = (
            collection_ref.where(filter=FieldFilter("aggregation_period", "==", "daily"))
            .where(filter=FieldFilter("date", ">=", month_start.isoformat()))
            .where(filter=FieldFilter("date", "<=", metrics_month_end(month_start).isoformat()))
            .stream()
        )
        per_owner: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
        while True:
            batch = list(islice(docs, METRICS_BATCH_SIZE))
            if not batch:
                break
            add_metrics_month_totals(per_owner, [deserialize_metrics_row(doc.to_dict()) for doc in batch])

        # Added up per owner and component over the month, so a user of several days is one user of the month
        return self._write_aggregate_metrics_rows(
            aggregate_metrics_collection_ref,
            build_aggregate_metrics_month_rows(month_start, per_owner),
            rows_changed=False,
            read_version=read_version,
            refreshes_collection_ref=refreshes_collection_ref,
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
            log_error(f"Exception calculating metrics: {str(e)}")
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
        collection_ref = self._get_collection(table_type="component_metrics", create_collection_if_not_found=True)
        aggregate_metrics_collection_ref = self._get_collection(
            table_type="aggregate_metrics", create_collection_if_not_found=True
        )
        refreshes_collection_ref = self._get_collection(
            table_type="metrics_refreshes", create_collection_if_not_found=True
        )
        sessions_collection_ref = self._get_collection(table_type="sessions")
        if (
            collection_ref is None
            or aggregate_metrics_collection_ref is None
            or refreshes_collection_ref is None
            or sessions_collection_ref is None
        ):
            log_info("No session data found. Won't calculate metrics.")
            return []
        runs_collection_ref = self._get_collection(table_type="runs")

        if rebuild_from is not None:
            # Reopened as a write reopens a day, before the claim, so a calculation another process is running
            # leaves them to the next one
            try:
                reopen_metrics_days_from(self.db_client, aggregate_metrics_collection_ref, rebuild_from)
                # Yesterday and today are picked by the fingerprint, so it is marked for the next one too
                if not self._mark_metrics_refresh_rebuild(refreshes_collection_ref):
                    return None
            except Exception as e:
                # Failed before the claim, so the refresh status shows it
                self._release_metrics_refresh(
                    refreshes_collection_ref,
                    None,
                    error=database_error_message(e),
                )
                raise

        worker_id = str(uuid4())
        # Claimed before anything is read, so a process that finds another calculating reads nothing
        refresh_row = self._claim_metrics_refresh(refreshes_collection_ref, worker_id)
        if refresh_row is None:
            return None

        try:
            dates_to_process, fingerprint = self._get_metrics_dates_to_calculate(
                aggregate_metrics_collection_ref,
                sessions_collection_ref,
                runs_collection_ref,
                refresh_row,
                rebuild_from,
            )

            legacy_runs_by_day: Dict[date, List[Dict[str, Any]]] = {}
            legacy_runs_by_id: Dict[str, Dict[str, Any]] = {}
            # Read once for every day until the v3.0.0 migration is stamped: no index finds one day's legacy runs
            if dates_to_process and packaging_version.parse(
                self.get_latest_schema_version(self.session_table_name) or "2.0.0"
            ) < packaging_version.parse("3.0.0"):
                start_timestamp = int(
                    datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
                )
                end_timestamp = int(
                    datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
                legacy_runs_by_day, legacy_runs_by_id = self._get_metrics_legacy_runs(
                    sessions_collection_ref, runs_collection_ref, start_timestamp, end_timestamp
                )
                if not transactional(self._heartbeat_metrics_refresh)(
                    self.db_client.transaction(), refreshes_collection_ref, worker_id
                ):
                    return None
                # A legacy run is dated on its own day, which may hold no session or run of the collections
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
                    self._release_metrics_refresh(refreshes_collection_ref, worker_id, stopped=True)
                    return None
                if not self._calculate_date_metrics(
                    collection_ref,
                    aggregate_metrics_collection_ref,
                    sessions_collection_ref,
                    runs_collection_ref,
                    date_to_process,
                    legacy_runs_by_day.get(date_to_process, []),
                    legacy_runs_by_id,
                    refreshes_collection_ref,
                    worker_id,
                    should_stop,
                ):
                    if should_stop is not None and should_stop():
                        self._release_metrics_refresh(refreshes_collection_ref, worker_id, stopped=True)
                    return None
                calculated_dates.append(date_to_process)

            # A month row is read only once completed, so a month is built only once its last day can be completed
            month_starts = sorted(
                month_start
                for month_start in set(get_months_to_calculate_metrics_for(calculated_dates))
                | set(self._get_open_metrics_months(aggregate_metrics_collection_ref))
                if metrics_day_completed(metrics_month_end(month_start))
            )
            for month_start in month_starts:
                if should_stop is not None and should_stop():
                    self._release_metrics_refresh(refreshes_collection_ref, worker_id, stopped=True)
                    return None
                if not self._calculate_month_metrics(
                    collection_ref, aggregate_metrics_collection_ref, month_start, refreshes_collection_ref, worker_id
                ):
                    return None

        except Exception as e:
            self._release_metrics_refresh(refreshes_collection_ref, worker_id, error=database_error_message(e))
            raise

        self._release_metrics_refresh(
            refreshes_collection_ref,
            worker_id,
            fingerprint=fingerprint,
            claimed_fingerprint=refresh_row["fingerprint"],
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
        collection_ref = self._get_collection(table_type="component_metrics")
        if collection_ref is None:
            return [], None

        query = collection_ref.where(filter=FieldFilter("aggregation_period", "==", "daily"))
        if starting_date:
            query = query.where(filter=FieldFilter("date", ">=", starting_date.isoformat()))
        if ending_date:
            query = query.where(filter=FieldFilter("date", "<=", ending_date.isoformat()))
        if user_id is not None:
            query = query.where(filter=FieldFilter("user_id", "==", user_id))
        rows = [deserialize_metrics_row(doc.to_dict()) for doc in query.select(list(METRICS_BY_OWNER_FIELDS)).stream()]
        if not rows:
            return [], None

        latest_updated_at = max((row["updated_at"] for row in rows if row.get("updated_at") is not None), default=None)
        return build_metrics_by_owner_from_rows(rows), latest_updated_at

    def _get_aggregate_metrics_rows(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the day rows of the aggregate metrics collection in the shape of the metrics table: the everyone rows for
        ``""``, one user's rows for a name, and every user's rows for ``None``."""
        aggregate_metrics_collection_ref = self._get_collection(table_type="aggregate_metrics")
        if aggregate_metrics_collection_ref is None:
            return [], None

        query = aggregate_metrics_collection_ref.where(filter=FieldFilter("aggregation_period", "==", "daily"))
        if starting_date:
            query = query.where(filter=FieldFilter("date", ">=", starting_date.isoformat()))
        if ending_date:
            query = query.where(filter=FieldFilter("date", "<=", ending_date.isoformat()))
        if user_id is not None:
            query = query.where(filter=FieldFilter("user_id", "==", user_id))
        # Only what build_metrics_from_aggregate_metrics reads, so the maps of timings are never decoded
        rows = [
            deserialize_metrics_row(doc.to_dict()) for doc in query.select(list(AGGREGATE_METRICS_ROWS_FIELDS)).stream()
        ]
        # Every user's rows are read with the everyone rows, one per day, which a filter on user_id would need an index
        # of its own to leave out
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

    def _metrics_calculated(self, refreshes_collection_ref) -> bool:
        """Whether the first calculate_metrics has finished, so reads take the metrics collections over
        agno_metrics."""
        refresh_row = (
            self._get_metrics_refresh_row(refreshes_collection_ref)[0] if refreshes_collection_ref is not None else None
        )
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
            # deprecated metrics collection
            if not metrics_calculation_enabled() or not self._metrics_calculated(
                self._get_collection(table_type="metrics_refreshes")
            ):
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

        Metrics are read from the aggregate metrics and component metrics once the first calculate_metrics has finished,
        and from the deprecated metrics collection until then. They are refreshed first, at most once per minute per
        process, unless stop_metrics_refresh_on_read was called.

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.
            user_id (Optional[str]): If set, only return that user's bucket. ``None`` returns every bucket.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            self._refresh_metrics_before_read()
            if self._metrics_calculated(self._get_collection(table_type="metrics_refreshes")):
                return self._get_metrics_rows(starting_date, ending_date, user_id)

            # Read without _get_collection, which would create the deprecated collection and its indexes
            query: Any = self.db_client.collection(self.metrics_table_name)
            if starting_date:
                query = query.where(filter=FieldFilter("date", ">=", starting_date.isoformat()))
            if ending_date:
                query = query.where(filter=FieldFilter("date", "<=", ending_date.isoformat()))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))

            docs = [doc.to_dict() for doc in query.stream()]
            # Records written before ownership existed hold a whole day, and only an
            # unscoped read sees them: an owner filter excludes them already
            if user_id is None:
                docs = drop_legacy_metrics(docs)

            records = []
            latest_updated_at = 0

            for data in docs:
                # Map the sentinel empty-string user_id back to None.
                if data.get("user_id") == "":
                    data["user_id"] = None
                records.append(data)
                updated_at = data.get("updated_at", 0)
                if updated_at > latest_updated_at:
                    latest_updated_at = updated_at

            if not records:
                return [], None

            return records, latest_updated_at

        except Exception as e:
            log_error(f"Exception getting metrics: {str(e)}")
            raise e

    def get_metrics_by_date(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of every user, one row per day, matching the given date range.

        Read from the everyone rows of the aggregate metrics once the first calculate_metrics has finished, and from the
        deprecated metrics collection until then. They are refreshed first, as get_metrics does.

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            self._refresh_metrics_before_read()
            if self._metrics_calculated(self._get_collection(table_type="metrics_refreshes")):
                return self._get_aggregate_metrics_rows(starting_date, ending_date, "")
            return super().get_metrics_by_date(starting_date, ending_date)

        except Exception as e:
            log_error(f"Exception getting metrics: {str(e)}")
            raise e

    def get_metrics_refresh_status(self) -> Optional[Dict[str, Any]]:
        """Get the status of the most recent calculate_metrics, from the metrics refreshes collection.

        Returns:
            Optional[Dict[str, Any]]: The status ('running', 'completed' or 'failed'), when it started and finished,
                and its error. None before the first calculation.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            refreshes_collection_ref = self._get_collection(table_type="metrics_refreshes")
            if refreshes_collection_ref is None:
                return None
            return metrics_refresh_status(*self._get_metrics_refresh_row(refreshes_collection_ref))

        except Exception as e:
            log_error(f"Exception getting metrics refresh status: {str(e)}")
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
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with
                no user.
            fields (List[str]): The columns to total.
            use_month_rows (bool): Total a calendar month inside the date range from its month aggregate metrics row, as
                one date.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each date, and when they were last updated.
        """
        aggregate_metrics_collection_ref = self._get_collection(table_type="aggregate_metrics")
        # Every owner is read from the everyone rows and a user from the user's rows; the runs with no user have no
        # aggregate metrics row of their own, so they are read from their component rows
        collection_ref = (
            self._get_collection(table_type="component_metrics") if user_id == "" else aggregate_metrics_collection_ref
        )
        if aggregate_metrics_collection_ref is None or collection_ref is None:
            return [], None

        # The component metrics collection keeps day rows only, so the runs with no user are read day by day
        full_months = metrics_full_months(starting_date, ending_date) if use_month_rows and user_id != "" else []

        @transactional
        def _read_records(transaction) -> Tuple[List[Dict[str, Any]], List[date]]:
            month_starts: List[date] = []
            if full_months:
                # Only a completed month's row stands for its days; an open one, reopened by a day rebuilt since
                # or not yet built, is read from its days. The full months follow each other, so a range finds them
                # however long the window is
                months_query = (
                    aggregate_metrics_collection_ref.where(filter=FieldFilter("aggregation_period", "==", "monthly"))
                    .where(filter=FieldFilter("user_id", "==", ""))
                    .where(filter=FieldFilter("completed", "==", True))
                    .where(filter=FieldFilter("date", ">=", full_months[0].isoformat()))
                    .where(filter=FieldFilter("date", "<=", full_months[-1].isoformat()))
                    .select(["date"])
                )
                month_starts = sorted(
                    deserialize_metrics_row(doc.to_dict())["date"]
                    for doc in months_query.stream(transaction=transaction)
                )

            queries = [
                collection_ref.where(filter=FieldFilter("aggregation_period", "==", "daily"))
                .where(filter=FieldFilter("date", ">=", first_day.isoformat()))
                .where(filter=FieldFilter("date", "<=", last_day.isoformat()))
                for first_day, last_day in metrics_day_ranges(starting_date, ending_date, month_starts)
            ]
            if month_starts:
                queries.append(
                    collection_ref.where(filter=FieldFilter("aggregation_period", "==", "monthly"))
                    .where(filter=FieldFilter("date", ">=", month_starts[0].isoformat()))
                    .where(filter=FieldFilter("date", "<=", month_starts[-1].isoformat()))
                )

            records: List[Dict[str, Any]] = []
            for query in queries:
                query = query.where(filter=FieldFilter("user_id", "==", user_id or "")).select(
                    metrics_rows_fields(fields)
                )
                records.extend(deserialize_metrics_row(doc.to_dict()) for doc in query.stream(transaction=transaction))
            return records, month_starts

        # One snapshot for every query of the read, so a rebuild writing between them is never half seen
        records, month_starts = _read_records(self.db_client.transaction(read_only=True))
        return total_metrics_rows(records, starting_date, ending_date, fields, month_starts)

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
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with
                no user.
            fields (Optional[List[str]]): The columns to total. ``None`` totals all.

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
            log_error(f"Exception getting component metrics: {str(e)}")
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
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with
                no user.
            fields (Optional[List[str]]): The columns to total. ``None`` totals all.

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
            log_error(f"Exception getting metrics totals: {str(e)}")
            raise e

    def get_metrics_versions(self, starting_date: date, ending_date: date) -> Optional[Dict[str, int]]:
        """Get the version of every everyone row of a day or a month of the aggregate metrics in the given date range.

        Metrics are refreshed first, as get_metrics refreshes them.

        Args:
            starting_date (date): The first day of the date range.
            ending_date (date): The last day of the date range.

        Returns:
            Optional[Dict[str, int]]: The version of each everyone row, keyed by its aggregation period and date. The
                same again only while no calculation wrote a row of the date range. ``None`` until the first
                calculate_metrics has finished, or without an aggregate metrics collection: a read would find no rows to
                total.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            self._refresh_metrics_before_read()
            aggregate_metrics_collection_ref = self._get_collection(table_type="aggregate_metrics")
            if aggregate_metrics_collection_ref is None or not self._metrics_calculated(
                self._get_collection(table_type="metrics_refreshes")
            ):
                return None

            docs = (
                aggregate_metrics_collection_ref.where(filter=FieldFilter("user_id", "==", ""))
                .where(filter=FieldFilter("date", ">=", starting_date.isoformat()))
                .where(filter=FieldFilter("date", "<=", ending_date.isoformat()))
                .select(["aggregation_period", "date", "version"])
                .stream()
            )
            return metrics_versions([SimpleNamespace(**deserialize_metrics_row(doc.to_dict())) for doc in docs])

        except Exception as e:
            log_error(f"Exception getting metrics versions: {str(e)}")
            raise e

    # -- Knowledge methods --

    # Firestore has no OR predicate, so ``user_id == X OR user_id IS NULL`` is post-filtered in Python.
    @staticmethod
    def _knowledge_row_is_visible(row: KnowledgeRow, user_id: Optional[str]) -> bool:
        if user_id is None:
            return True
        owner = getattr(row, "user_id", None)
        return owner is None or owner == user_id

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): If set, only delete rows owned by this user; unowned rows are shared.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection_ref = self._get_collection(table_type="knowledge")
            docs = list(collection_ref.where(filter=FieldFilter("id", "==", id)).stream())

            for doc in docs:
                if user_id is not None:
                    data = doc.to_dict() or {}
                    if data.get("user_id") != user_id:
                        continue
                doc.reference.delete()

        except Exception as e:
            log_error(f"Error deleting knowledge content: {str(e)}")
            raise e

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): If set, only return the row if owned by this user or unowned.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            collection_ref = self._get_collection(table_type="knowledge")
            docs = collection_ref.where(filter=FieldFilter("id", "==", id)).stream()

            for doc in docs:
                data = doc.to_dict()
                row = KnowledgeRow.model_validate(data)
                if not self._knowledge_row_is_visible(row, user_id):
                    return None
                return row

            return None

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
            user_id (Optional[str]): If set, only return rows owned by this user or unowned.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            collection_ref = self._get_collection(table_type="knowledge")
            if collection_ref is None:
                return [], 0

            query = collection_ref

            # Apply linked_to filter if provided
            if linked_to is not None:
                query = query.where("linked_to", "==", linked_to)

            # Apply sorting
            query = apply_sorting(query, sort_by, sort_order)

            # Owner scoping is post-filtered in memory, so defer pagination or it slices the unfiltered set.
            if user_id is None:
                query = apply_pagination(query, limit, page)

            docs = query.stream()
            records = []
            for doc in docs:
                records.append(doc.to_dict())

            knowledge_rows = [KnowledgeRow.model_validate(record) for record in records]
            if user_id is not None:
                knowledge_rows = [r for r in knowledge_rows if self._knowledge_row_is_visible(r, user_id)]
                total_count = len(knowledge_rows)
                if limit:
                    start = (page - 1) * limit if (page and page > 1) else 0
                    knowledge_rows = knowledge_rows[start : start + limit]
            else:
                total_count = len(knowledge_rows)

            return knowledge_rows, total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {str(e)}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        try:
            collection_ref = self._get_collection(table_type="knowledge", create_collection_if_not_found=True)
            if collection_ref is None:
                return None

            update_doc = knowledge_row.model_dump()

            # Find existing document or create new one
            docs = collection_ref.where(filter=FieldFilter("id", "==", knowledge_row.id)).stream()
            existing = next((doc for doc in docs), None)

            # A scoped write must not overwrite a doc it does not own
            if existing is not None and knowledge_row.user_id is not None:
                if (existing.to_dict() or {}).get("user_id") != knowledge_row.user_id:
                    raise ValueError(f"Knowledge content {knowledge_row.id} not found")

            doc_ref = existing.reference if existing is not None else collection_ref.document()

            doc_ref.set(update_doc, merge=True)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge content: {str(e)}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database."""
        try:
            collection_ref = self._get_collection(table_type="evals", create_collection_if_not_found=True)

            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            doc_ref = collection_ref.document()
            doc_ref.set(eval_dict)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            raise e

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the database."""
        try:
            collection_ref = self._get_collection(table_type="evals")
            docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()

            deleted_count = 0
            for doc in docs:
                doc.reference.delete()
                deleted_count += 1

            if deleted_count == 0:
                log_info(f"No eval run found with ID: {eval_run_id}")
            else:
                log_info(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {str(e)}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple eval runs from the database.

        Args:
            eval_run_ids (List[str]): The IDs of the eval runs to delete.
            user_id (Optional[str]): If set, only delete runs owned by this user.

        Raises:
            Exception: If there is an error deleting the eval runs.
        """
        try:
            collection_ref = self._get_collection(table_type="evals")
            batch = self.db_client.batch()
            deleted_count = 0

            for eval_run_id in eval_run_ids:
                docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()
                for doc in docs:
                    if user_id is not None and doc.to_dict().get("user_id") != user_id:
                        continue
                    batch.delete(doc.reference)
                    deleted_count += 1

            batch.commit()

            if deleted_count == 0:
                log_info(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_info(f"Deleted {deleted_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")
            raise e

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to get.
            deserialize (Optional[bool]): Whether to deserialize the eval run. Defaults to True.
            user_id (Optional[str]): If set, only return the run if owned by this user.

        Returns:
            Optional[Union[EvalRunRecord, Dict[str, Any]]]:
                - When deserialize=True: EvalRunRecord object
                - When deserialize=False: EvalRun dictionary

        Raises:
            Exception: If there is an error getting the eval run.
        """
        try:
            collection_ref = self._get_collection(table_type="evals")
            if not collection_ref:
                return None

            docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()

            eval_run_raw = None
            for doc in docs:
                eval_run_raw = doc.to_dict()
                break

            if not eval_run_raw:
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
        """Get all eval runs from the database.

        Args:
            limit (Optional[int]): The maximum number of eval runs to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The order to sort by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            workflow_id (Optional[str]): The ID of the workflow to filter by.
            model_id (Optional[str]): The ID of the model to filter by.
            user_id (Optional[str]): If set, only return runs owned by this user.
            eval_type (Optional[List[EvalType]]): The type of eval to filter by.
            filter_type (Optional[EvalFilterType]): The type of filter to apply.
            deserialize (Optional[bool]): Whether to deserialize the eval runs. Defaults to True.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of eval run dictionaries and the total count

        Raises:
            Exception: If there is an error getting the eval runs.
        """
        try:
            collection_ref = self._get_collection(table_type="evals")
            if collection_ref is None:
                return [] if deserialize else ([], 0)

            query = collection_ref

            if agent_id is not None:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id is not None:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if workflow_id is not None:
                query = query.where(filter=FieldFilter("workflow_id", "==", workflow_id))
            if model_id is not None:
                query = query.where(filter=FieldFilter("model_id", "==", model_id))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if eval_type is not None and len(eval_type) > 0:
                eval_values = [et.value for et in eval_type]
                query = query.where(filter=FieldFilter("eval_type", "in", eval_values))

            # Apply default sorting by created_at desc if no sort parameters provided
            if sort_by is None:
                from google.cloud.firestore import Query

                query = query.order_by("created_at", direction=Query.DESCENDING)
            else:
                query = apply_sorting(query, sort_by, sort_order)

            # Get all documents for counting before pagination
            all_docs = query.stream()
            all_records = [doc.to_dict() for doc in all_docs]

            # Filter by component type in Python. Firestore would require the
            # inequality field to also be the first sort field, breaking the
            # created_at ordering.
            if filter_type is not None:
                if filter_type == EvalFilterType.AGENT:
                    all_records = [record for record in all_records if record.get("agent_id") is not None]
                elif filter_type == EvalFilterType.TEAM:
                    all_records = [record for record in all_records if record.get("team_id") is not None]
                elif filter_type == EvalFilterType.WORKFLOW:
                    all_records = [record for record in all_records if record.get("workflow_id") is not None]

            if not all_records:
                return [] if deserialize else ([], 0)

            # Get total count before pagination
            total_count = len(all_records)

            # Apply pagination to the results
            if limit is not None and page is not None:
                start_index = (page - 1) * limit
                end_index = start_index + limit
                records = all_records[start_index:end_index]
            elif limit is not None:
                records = all_records[:limit]
            else:
                records = all_records

            if not deserialize:
                return records, total_count

            return [EvalRunRecord.model_validate(row) for row in records]

        except Exception as e:
            log_error(f"Exception getting eval runs: {str(e)}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Update the name of an eval run in the database.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            name (str): The new name of the eval run.
            deserialize (Optional[bool]): Whether to deserialize the eval run. Defaults to True.
            user_id (Optional[str]): If set, only rename the run if owned by this user.

        Returns:
            Optional[Union[EvalRunRecord, Dict[str, Any]]]:
                - When deserialize=True: EvalRunRecord object
                - When deserialize=False: EvalRun dictionary

        Raises:
            Exception: If there is an error updating the eval run.
        """
        try:
            collection_ref = self._get_collection(table_type="evals")
            if not collection_ref:
                return None

            docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()
            doc = next(iter(docs), None)

            if doc is None:
                return None
            if user_id is not None and doc.to_dict().get("user_id") != user_id:
                return None

            doc_ref = doc.reference
            doc_ref.update({"name": name, "updated_at": int(time.time())})

            updated_doc = doc_ref.get()
            if not updated_doc.exists:
                return None

            result = updated_doc.to_dict()

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not result or not deserialize:
                return result

            return EvalRunRecord.model_validate(result)

        except Exception as e:
            log_error(f"Error updating eval run name {eval_run_id}: {str(e)}")
            raise e

    def update_eval_run_user_id(self, eval_run_id: str, user_id: str) -> None:
        """Set the owner (user_id) on an existing eval run.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            user_id (str): The owner to set.
        """
        try:
            collection_ref = self._get_collection(table_type="evals")
            if not collection_ref:
                return

            docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()
            doc_ref = next((doc.reference for doc in docs), None)
            if doc_ref is None:
                return

            doc_ref.update({"user_id": user_id})

        except Exception as e:
            log_error(f"Error setting owner on eval run {eval_run_id}: {str(e)}")
            raise e

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            collection_ref = self._get_collection(table_type="traces", create_collection_if_not_found=True)
            if collection_ref is None:
                return

            # Check if trace already exists
            docs = collection_ref.where(filter=FieldFilter("trace_id", "==", trace.trace_id)).limit(1).stream()
            existing_doc = None
            existing_data = None
            for doc in docs:
                existing_doc = doc
                existing_data = doc.to_dict()
                break

            if existing_data and existing_doc is not None:
                # Update existing trace
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
                    existing_data.get("workflow_id"),
                    existing_data.get("team_id"),
                    existing_data.get("agent_id"),
                    existing_data.get("name", ""),
                )
                new_level = get_component_level(trace.workflow_id, trace.team_id, trace.agent_id, trace.name)
                should_update_name = new_level > existing_level

                # Parse existing start_time to calculate correct duration
                existing_start_time_str = existing_data.get("start_time")
                if isinstance(existing_start_time_str, str):
                    existing_start_time = datetime.fromisoformat(existing_start_time_str.replace("Z", "+00:00"))
                else:
                    existing_start_time = trace.start_time

                recalculated_duration_ms = int((trace.end_time - existing_start_time).total_seconds() * 1000)

                update_values: Dict[str, Any] = {
                    "end_time": trace.end_time.isoformat(),
                    "duration_ms": recalculated_duration_ms,
                    "status": trace.status,
                }

                if should_update_name:
                    update_values["name"] = trace.name

                # Preserve existing non-null context values: only fill in fields
                # that the existing row left blank. Otherwise a later upsert from
                # a child span (e.g. a post-hook agent's run with a different
                # session_id) would overwrite the trace's already-correct context.
                if existing_data.get("run_id") is None and trace.run_id is not None:
                    update_values["run_id"] = trace.run_id
                if existing_data.get("session_id") is None and trace.session_id is not None:
                    update_values["session_id"] = trace.session_id
                if existing_data.get("user_id") is None and trace.user_id is not None:
                    update_values["user_id"] = trace.user_id
                if existing_data.get("agent_id") is None and trace.agent_id is not None:
                    update_values["agent_id"] = trace.agent_id
                if existing_data.get("team_id") is None and trace.team_id is not None:
                    update_values["team_id"] = trace.team_id
                if existing_data.get("workflow_id") is None and trace.workflow_id is not None:
                    update_values["workflow_id"] = trace.workflow_id

                existing_doc.reference.update(update_values)
            else:
                # Create new trace with initialized counters
                trace_dict = trace.to_dict()
                trace_dict["total_spans"] = 0
                trace_dict["error_count"] = 0
                collection_ref.add(trace_dict)

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

            collection_ref = self._get_collection(table_type="traces")
            if collection_ref is None:
                return None

            if trace_id:
                docs = collection_ref.where(filter=FieldFilter("trace_id", "==", trace_id)).limit(1).stream()
            elif run_id:
                from google.cloud.firestore import Query

                docs = (
                    collection_ref.where(filter=FieldFilter("run_id", "==", run_id))
                    .order_by("start_time", direction=Query.DESCENDING)
                    .limit(1)
                    .stream()
                )
            else:
                log_debug("get_trace called without any filter parameters")
                return None

            for doc in docs:
                trace_data = doc.to_dict()
                # Use stored values (default to 0 if not present)
                trace_data.setdefault("total_spans", 0)
                trace_data.setdefault("error_count", 0)
                return Trace.from_dict(trace_data)

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

            collection_ref = self._get_collection(table_type="traces")
            if collection_ref is None:
                return [], 0

            query = collection_ref

            # Apply filters
            if run_id:
                query = query.where(filter=FieldFilter("run_id", "==", run_id))
            if session_id:
                query = query.where(filter=FieldFilter("session_id", "==", session_id))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if workflow_id:
                query = query.where(filter=FieldFilter("workflow_id", "==", workflow_id))
            if status:
                query = query.where(filter=FieldFilter("status", "==", status))
            if start_time:
                query = query.where(filter=FieldFilter("start_time", ">=", start_time.isoformat()))
            if end_time:
                query = query.where(filter=FieldFilter("end_time", "<=", end_time.isoformat()))

            # Get all matching documents
            docs = query.stream()
            all_records = [doc.to_dict() for doc in docs]

            # Sort by start_time descending
            all_records.sort(key=lambda x: x.get("start_time", ""), reverse=True)

            # Get total count
            total_count = len(all_records)

            # Apply pagination
            if limit and page:
                offset = (page - 1) * limit
                paginated_records = all_records[offset : offset + limit]
            elif limit:
                paginated_records = all_records[:limit]
            else:
                paginated_records = all_records

            # Convert to Trace objects with stored span counts
            traces = []
            for trace_data in paginated_records:
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
            collection_ref = self._get_collection(table_type="traces")
            if collection_ref is None:
                return [], 0

            query = collection_ref

            # Apply filters
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if workflow_id:
                query = query.where(filter=FieldFilter("workflow_id", "==", workflow_id))
            if start_time:
                query = query.where(filter=FieldFilter("created_at", ">=", start_time.isoformat()))
            if end_time:
                query = query.where(filter=FieldFilter("created_at", "<=", end_time.isoformat()))

            # Get all matching documents
            docs = query.stream()

            # Aggregate by session_id
            session_stats: Dict[str, Dict[str, Any]] = {}
            for doc in docs:
                trace_data = doc.to_dict()
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
            if limit and page:
                offset = (page - 1) * limit
                paginated_stats = stats_list[offset : offset + limit]
            elif limit:
                paginated_stats = stats_list[:limit]
            else:
                paginated_stats = stats_list

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
            collection_ref = self._get_collection(table_type="spans", create_collection_if_not_found=True)
            if collection_ref is None:
                return

            span_dict = span.to_dict()
            # Serialize attributes as JSON string
            if "attributes" in span_dict and isinstance(span_dict["attributes"], dict):
                span_dict["attributes"] = json.dumps(span_dict["attributes"])

            collection_ref.add(span_dict)

            # Increment total_spans and error_count on trace
            traces_collection = self._get_collection(table_type="traces")
            if traces_collection:
                try:
                    docs = (
                        traces_collection.where(filter=FieldFilter("trace_id", "==", span.trace_id)).limit(1).stream()
                    )
                    for doc in docs:
                        trace_data = doc.to_dict()
                        current_total = trace_data.get("total_spans", 0)
                        current_errors = trace_data.get("error_count", 0)

                        update_values = {"total_spans": current_total + 1}
                        if span.status_code == "ERROR":
                            update_values["error_count"] = current_errors + 1

                        doc.reference.update(update_values)
                        break
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
            collection_ref = self._get_collection(table_type="spans", create_collection_if_not_found=True)
            if collection_ref is None:
                return

            # Firestore batch has a limit of 500 operations
            batch = self.db_client.batch()
            batch_count = 0

            for span in spans:
                span_dict = span.to_dict()
                # Serialize attributes as JSON string
                if "attributes" in span_dict and isinstance(span_dict["attributes"], dict):
                    span_dict["attributes"] = json.dumps(span_dict["attributes"])

                doc_ref = collection_ref.document()
                batch.set(doc_ref, span_dict)
                batch_count += 1

                # Commit batch if reaching limit
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db_client.batch()
                    batch_count = 0

            # Commit remaining operations
            if batch_count > 0:
                batch.commit()

            # Update trace with total_spans and error_count
            trace_id = spans[0].trace_id
            spans_count = len(spans)
            error_count = sum(1 for s in spans if s.status_code == "ERROR")

            traces_collection = self._get_collection(table_type="traces")
            if traces_collection:
                try:
                    docs = traces_collection.where(filter=FieldFilter("trace_id", "==", trace_id)).limit(1).stream()
                    for doc in docs:
                        trace_data = doc.to_dict()
                        current_total = trace_data.get("total_spans", 0)
                        current_errors = trace_data.get("error_count", 0)

                        doc.reference.update(
                            {
                                "total_spans": current_total + spans_count,
                                "error_count": current_errors + error_count,
                            }
                        )
                        break
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

            collection_ref = self._get_collection(table_type="spans")
            if collection_ref is None:
                return None

            docs = collection_ref.where(filter=FieldFilter("span_id", "==", span_id)).limit(1).stream()

            for doc in docs:
                span_data = doc.to_dict()
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

            collection_ref = self._get_collection(table_type="spans")
            if collection_ref is None:
                return []

            query = collection_ref

            if trace_id:
                query = query.where(filter=FieldFilter("trace_id", "==", trace_id))
            if parent_span_id:
                query = query.where(filter=FieldFilter("parent_span_id", "==", parent_span_id))

            if limit:
                query = query.limit(limit)

            docs = query.stream()

            spans = []
            for doc in docs:
                span_data = doc.to_dict()
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
        raise NotImplementedError("Learning methods not yet implemented for FirestoreDb")

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
        raise NotImplementedError("Learning methods not yet implemented for FirestoreDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for FirestoreDb")

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
        raise NotImplementedError("Learning methods not yet implemented for FirestoreDb")
