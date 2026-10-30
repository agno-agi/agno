import re
import time
from datetime import date, datetime, timedelta, timezone
from importlib import metadata
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Set, Tuple, Union
from uuid import uuid4

try:
    from pymongo.errors import DuplicateKeyError
except ImportError:
    DuplicateKeyError = Exception  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.mongo.utils import (
    OS_METRICS_BATCH_SIZE,
    OS_METRICS_IN_LIST_LIMIT,
    apply_pagination,
    apply_sorting,
    build_os_metrics_runs_projection,
    build_os_metrics_totals,
    build_os_metrics_totals_pipeline,
    bulk_upsert_metrics,
    bulk_upsert_os_metrics,
    calculate_date_metrics,
    create_collection_indexes,
    deserialize_os_metrics_row,
    extend_os_metrics_lock,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    lock_os_metrics,
    unlock_os_metrics,
    upsert_os_metrics_totals_row,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import (
    HISTORY_SKIP_STATUSES,
    add_month_os_metrics,
    build_os_metrics_totals_row,
    build_single_run_row,
    calculate_date_os_metrics,
    calculate_month_os_metrics,
    deserialize_run,
    deserialize_session,
    deserialize_session_json_fields,
    deserialize_sessions,
    drop_legacy_metrics,
    filter_context_runs,
    get_months_to_calculate_os_metrics_for,
    get_os_metrics_legacy_runs,
    get_os_metrics_records_by_day,
    merge_os_metrics_totals,
    merge_runs_table_with_legacy_blob,
    metrics_starting_date_from_days,
    os_metrics_day_completed,
    os_metrics_full_months,
    os_metrics_month_end,
    os_metrics_nested_run_ids,
    os_metrics_rows_to_write,
    os_metrics_totals_row_to_write,
    resolve_os_metrics_fields,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    from pymongo import MongoClient, ReturnDocument
    from pymongo.collection import Collection
    from pymongo.database import Database
    from pymongo.driver_info import DriverInfo
    from pymongo.errors import OperationFailure
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it using `pip install pymongo`")

DRIVER_METADATA = DriverInfo(name="Agno", version=metadata.version("agno"))


class MongoDb(BaseDb):
    def __init__(
        self,
        db_client: Optional[MongoClient] = None,
        db_name: Optional[str] = None,
        db_url: Optional[str] = None,
        session_collection: Optional[str] = None,
        runs_collection: Optional[str] = None,
        memory_collection: Optional[str] = None,
        metrics_collection: Optional[str] = None,
        os_metrics_collection: Optional[str] = None,
        os_metrics_totals_collection: Optional[str] = None,
        eval_collection: Optional[str] = None,
        knowledge_collection: Optional[str] = None,
        traces_collection: Optional[str] = None,
        spans_collection: Optional[str] = None,
        schedules_collection: Optional[str] = None,
        schedule_runs_collection: Optional[str] = None,
        learnings_collection: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a MongoDB database.

        Args:
            db_client (Optional[MongoClient]): The MongoDB client to use.
            db_name (Optional[str]): The name of the database to use.
            db_url (Optional[str]): The database URL to connect to.
            session_collection (Optional[str]): Name of the collection to store sessions.
            runs_collection (Optional[str]): Name of the collection to store runs (one document per run).
            memory_collection (Optional[str]): Name of the collection to store memories.
            metrics_collection (Optional[str]): Name of the collection to store metrics.
            os_metrics_collection (Optional[str]): Name of the collection to store OS metrics.
            os_metrics_totals_collection (Optional[str]): Name of the collection to store the OS metrics totals.
            eval_collection (Optional[str]): Name of the collection to store evaluation runs.
            knowledge_collection (Optional[str]): Name of the collection to store knowledge documents.
            traces_collection (Optional[str]): Name of the collection to store traces.
            spans_collection (Optional[str]): Name of the collection to store spans.
            schedules_collection (Optional[str]): Name of the collection to store schedules.
            schedule_runs_collection (Optional[str]): Name of the collection to store schedule runs.
            learnings_collection (Optional[str]): Name of the collection to store learnings.
            id (Optional[str]): ID of the database.

        Raises:
            ValueError: If neither db_url nor db_client is provided.
        """
        if id is None:
            base_seed = db_url or str(db_client)
            db_name_suffix = db_name if db_name is not None else "agno"
            seed = f"{base_seed}#{db_name_suffix}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_collection,
            runs_table=runs_collection,
            memory_table=memory_collection,
            metrics_table=metrics_collection,
            os_metrics_table=os_metrics_collection,
            os_metrics_totals_table=os_metrics_totals_collection,
            eval_table=eval_collection,
            knowledge_table=knowledge_collection,
            traces_table=traces_collection,
            spans_table=spans_collection,
            schedules_table=schedules_collection,
            schedule_runs_table=schedule_runs_collection,
            learnings_table=learnings_collection,
        )

        _client: Optional[MongoClient] = db_client
        if _client is None and db_url is not None:
            _client = MongoClient(db_url, driver=DRIVER_METADATA)
        if _client is None:
            raise ValueError("One of db_url or db_client must be provided")

        # append_metadata was added in PyMongo 4.14.0, but is a valid database name on earlier versions
        if callable(_client.append_metadata):
            _client.append_metadata(DRIVER_METADATA)

        self.db_url: Optional[str] = db_url
        self.db_client: MongoClient = _client

        self.db_name: str = db_name if db_name is not None else "agno"

        self._database: Optional[Database] = None

        # Zero means never refreshed; get_os_metrics uses this to refresh lazily, at most once per minute
        self._os_metrics_refreshed_at: float = 0.0
        # The sessions and runs the last refresh read, so a refresh with nothing new is skipped
        self._os_metrics_fingerprint: Optional[Tuple[Any, ...]] = None

    def close(self) -> None:
        """Close the MongoDB client connection.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self.db_client is not None:
            self.db_client.close()

    @property
    def database(self) -> Database:
        if self._database is None:
            self._database = self.db_client[self.db_name]
        return self._database

    # -- DB methods --
    def table_exists(self, table_name: str) -> bool:
        """Check if a collection with the given name exists in the MongoDB database.

        Args:
            table_name: Name of the collection to check

        Returns:
            bool: True if the collection exists in the database, False otherwise
        """
        return table_name in self.database.list_collection_names()

    def _create_all_tables(self):
        """Create all configured MongoDB collections if they don't exist."""
        collections_to_create = [
            ("sessions", self.session_table_name),
            ("runs", self.runs_table_name),
            ("memories", self.memory_table_name),
            ("metrics", self.metrics_table_name),
            ("os_metrics", self.os_metrics_table_name),
            ("os_metrics_totals", self.os_metrics_totals_table_name),
            ("evals", self.eval_table_name),
            ("knowledge", self.knowledge_table_name),
            ("schedules", self.schedules_table_name),
            ("schedule_runs", self.schedule_runs_table_name),
        ]

        for collection_type, collection_name in collections_to_create:
            if collection_name and not self.table_exists(collection_name):
                self._get_collection(collection_type, create_collection_if_not_found=True)

    def _get_collection(
        self, table_type: str, create_collection_if_not_found: Optional[bool] = True
    ) -> Optional[Collection]:
        """Get or create a collection based on table type.

        Args:
            table_type (str): The type of table to get or create.

        Returns:
            Collection: The collection object.
        """
        if table_type == "sessions":
            if not hasattr(self, "session_collection"):
                if self.session_table_name is None:
                    raise ValueError("Session collection was not provided on initialization")
                self.session_collection = self._get_or_create_collection(
                    collection_name=self.session_table_name,
                    collection_type="sessions",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.session_collection

        if table_type == "runs":
            # Use getattr+None so a failed read with create=False isn't sticky-cached
            if getattr(self, "runs_collection", None) is None:
                if self.runs_table_name is None:
                    raise ValueError("Runs collection was not provided on initialization")
                self.runs_collection = self._get_or_create_collection(
                    collection_name=self.runs_table_name,
                    collection_type="runs",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.runs_collection

        if table_type == "memories":
            if not hasattr(self, "memory_collection"):
                if self.memory_table_name is None:
                    raise ValueError("Memory collection was not provided on initialization")
                self.memory_collection = self._get_or_create_collection(
                    collection_name=self.memory_table_name,
                    collection_type="memories",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.memory_collection

        if table_type == "metrics":
            if not hasattr(self, "metrics_collection"):
                if self.metrics_table_name is None:
                    raise ValueError("Metrics collection was not provided on initialization")
                self.metrics_collection = self._get_or_create_collection(
                    collection_name=self.metrics_table_name,
                    collection_type="metrics",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.metrics_collection

        if table_type == "os_metrics":
            if not hasattr(self, "os_metrics_collection"):
                if self.os_metrics_table_name is None:
                    raise ValueError("OS metrics collection was not provided on initialization")
                self.os_metrics_collection = self._get_or_create_collection(
                    collection_name=self.os_metrics_table_name,
                    collection_type="os_metrics",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.os_metrics_collection

        if table_type == "os_metrics_totals":
            if not hasattr(self, "os_metrics_totals_collection"):
                if self.os_metrics_totals_table_name is None:
                    raise ValueError("OS metrics totals collection was not provided on initialization")
                self.os_metrics_totals_collection = self._get_or_create_collection(
                    collection_name=self.os_metrics_totals_table_name,
                    collection_type="os_metrics_totals",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.os_metrics_totals_collection

        if table_type == "evals":
            if not hasattr(self, "eval_collection"):
                if self.eval_table_name is None:
                    raise ValueError("Eval collection was not provided on initialization")
                self.eval_collection = self._get_or_create_collection(
                    collection_name=self.eval_table_name,
                    collection_type="evals",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.eval_collection

        if table_type == "knowledge":
            if not hasattr(self, "knowledge_collection"):
                if self.knowledge_table_name is None:
                    raise ValueError("Knowledge collection was not provided on initialization")
                self.knowledge_collection = self._get_or_create_collection(
                    collection_name=self.knowledge_table_name,
                    collection_type="knowledge",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.knowledge_collection

        if table_type == "traces":
            if not hasattr(self, "traces_collection"):
                if self.trace_table_name is None:
                    raise ValueError("Traces collection was not provided on initialization")
                self.traces_collection = self._get_or_create_collection(
                    collection_name=self.trace_table_name,
                    collection_type="traces",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.traces_collection

        if table_type == "spans":
            if not hasattr(self, "spans_collection"):
                if self.span_table_name is None:
                    raise ValueError("Spans collection was not provided on initialization")
                self.spans_collection = self._get_or_create_collection(
                    collection_name=self.span_table_name,
                    collection_type="spans",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.spans_collection

        if table_type == "learnings":
            # getattr(...) is None (not `not hasattr`) so a read with create=False that returns
            # None isn't cached and silently swallows later writes.
            if getattr(self, "learnings_collection", None) is None:
                if self.learnings_table_name is None:
                    raise ValueError("Learnings collection was not provided on initialization")
                self.learnings_collection = self._get_or_create_collection(
                    collection_name=self.learnings_table_name,
                    collection_type="learnings",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.learnings_collection

        if table_type == "schedules":
            if not hasattr(self, "schedules_collection"):
                if self.schedules_table_name is None:
                    raise ValueError("Schedules collection was not provided on initialization")
                self.schedules_collection = self._get_or_create_collection(
                    collection_name=self.schedules_table_name,
                    collection_type="schedules",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.schedules_collection

        if table_type == "schedule_runs":
            if not hasattr(self, "schedule_runs_collection"):
                if self.schedule_runs_table_name is None:
                    raise ValueError("Schedule runs collection was not provided on initialization")
                self.schedule_runs_collection = self._get_or_create_collection(
                    collection_name=self.schedule_runs_table_name,
                    collection_type="schedule_runs",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.schedule_runs_collection

        raise ValueError(f"Unknown table type: {table_type}")

    def _get_or_create_collection(
        self, collection_name: str, collection_type: str, create_collection_if_not_found: Optional[bool] = True
    ) -> Optional[Collection]:
        """Get or create a collection with proper indexes.

        Args:
            collection_name (str): The name of the collection to get or create.
            collection_type (str): The type of collection to get or create.
            create_collection_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Optional[Collection]: The collection object.
        """
        try:
            collection = self.database[collection_name]

            if not hasattr(self, f"_{collection_name}_initialized"):
                if not create_collection_if_not_found:
                    return None
                create_collection_indexes(collection, collection_type)
                setattr(self, f"_{collection_name}_initialized", True)
                log_debug(f"Initialized collection '{collection_name}'")
            else:
                log_debug(f"Collection '{collection_name}' already initialized")

            return collection

        except Exception as e:
            log_error(f"Error getting collection {collection_name}: {str(e)}")
            raise

    def get_latest_schema_version(self, table_name: str = "") -> Optional[str]:
        """Get the schema version stamped for the given table.

        Defaults to "2.0.0" when nothing is stamped so the MigrationManager
        runs migrations instead of skipping the table.
        """
        doc = self.database[self.versions_table_name].find_one({"table_name": table_name})
        if doc is None:
            return "2.0.0"
        return doc.get("version") or "2.0.0"

    def upsert_schema_version(self, table_name: str = "", version: str = "") -> None:
        """Record the schema version stamp for the given table."""
        self.database[self.versions_table_name].update_one(
            {"table_name": table_name},
            {"$set": {"table_name": table_name, "version": version, "updated_at": int(time.time())}},
            upsert=True,
        )

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
        collection = self._get_collection(table_type="sessions")
        if collection is None:
            log_info(f"{self.session_table_name} collection does not exist, nothing to clean up")
            return False

        if not force:
            pending = collection.count_documents({"runs": {"$exists": True, "$ne": None, "$not": {"$size": 0}}})
            if pending > 0:
                raise RuntimeError(
                    f"Refusing to unset {self.session_table_name}.runs: {pending} session(s) still have "
                    "non-null `runs` content. Run MigrationManager(db).up() first, or pass force=True."
                )

        log_info(f"Unsetting legacy runs field from {self.session_table_name} documents")
        result = collection.update_many(
            {"runs": {"$exists": True}},
            {"$unset": {"runs": ""}},
        )
        log_info(f"Unset runs on {result.modified_count} session document(s)")
        return result.modified_count > 0 or result.matched_count > 0

    # -- Run methods --
    def _get_session_runs_docs(
        self, runs_collection: Collection, session_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get the raw run_data dicts for the given session, in insertion order.

        When ``limit`` is set, push "most recent N context-relevant runs" down to
        the DB: drop member sub-runs (``parent_run_id`` set) and terminal-skip
        statuses, sort newest-first, take N, then reverse back to chronological
        order. ``$nin``/``None`` in Mongo also match a null or missing field, so
        this keeps runs whose ``status`` is null/absent — mirroring the SQL
        ``status IS NULL OR status NOT IN (...)`` fast path.
        """
        if limit is not None:
            pipeline: List[Dict[str, Any]] = [
                {
                    "$match": {
                        "session_id": session_id,
                        "parent_run_id": None,
                        "status": {"$nin": HISTORY_SKIP_STATUSES},
                    }
                },
                {
                    "$addFields": {
                        "_ri": {"$ifNull": ["$run_index", 0]},
                        "_ca": {"$ifNull": ["$created_at", 0]},
                    }
                },
                {"$sort": {"_ri": -1, "_ca": -1}},
                {"$limit": limit},
            ]
            docs = [doc["run_data"] for doc in runs_collection.aggregate(pipeline) if "run_data" in doc]
            docs.reverse()  # back to chronological order
            return docs

        pipeline = [
            {"$match": {"session_id": session_id}},
            {"$addFields": {"_ri": {"$ifNull": ["$run_index", 0]}, "_ca": {"$ifNull": ["$created_at", 0]}}},
            {"$sort": {"_ri": 1, "_ca": 1}},
        ]
        return [doc["run_data"] for doc in runs_collection.aggregate(pipeline) if "run_data" in doc]

    def _get_sessions_runs_docs(
        self, runs_collection: Collection, session_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get raw run_data dicts for several sessions, grouped by session_id."""
        if not session_ids:
            return {}
        cursor = runs_collection.find({"session_id": {"$in": session_ids}}).sort(
            [("session_id", 1), ("run_index", 1), ("created_at", 1)]
        )
        runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
        for doc in cursor:
            sid = doc.get("session_id")
            run_data = doc.get("run_data")
            if sid is None or run_data is None:
                continue
            runs_by_session.setdefault(sid, []).append(run_data)
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
            runs_collection = self._get_collection(table_type="runs", create_collection_if_not_found=True)
            if runs_collection is None:
                return

            row = build_single_run_row(
                run=run,
                session_id=session_id,
                user_id=user_id,
                run_index=run_index,
            )

            # Preserve the original run_index if the document already exists,
            # so reorders don't happen on status-only updates.
            existing = runs_collection.find_one({"run_id": row["run_id"]}, {"run_index": 1})
            if existing is not None and "run_index" in existing:
                row["run_index"] = existing["run_index"]

            runs_collection.replace_one({"run_id": row["run_id"]}, row, upsert=True)
        except Exception as e:
            log_error(f"Exception upserting run into runs collection: {str(e)}")
            raise e

    def get_run(
        self, run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]]]:
        """Read a single run from the runs collection."""
        try:
            collection = self._get_collection(table_type="runs")
            if collection is None:
                return None
            doc = collection.find_one({"run_id": run_id})
            if doc is None:
                return None
            if not deserialize:
                return doc
            return deserialize_run(doc.get("run_type"), doc["run_data"])
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
            collection = self._get_collection(table_type="runs")
            if collection is None:
                return [] if deserialize else ([], 0)

            query: Dict[str, Any] = {}
            if session_id is not None:
                query["session_id"] = session_id
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if workflow_id is not None:
                query["workflow_id"] = workflow_id
            if status is not None:
                query["status"] = status.value if isinstance(status, RunStatus) else status

            total_count = collection.count_documents(query)

            cursor = collection.find(query)
            sort_criteria = apply_sorting({}, sort_by, sort_order)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)
            else:
                cursor = cursor.sort([("run_index", 1), ("created_at", 1)])

            query_args = apply_pagination({}, limit, page)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            run_rows = list(cursor)

            if not deserialize:
                return run_rows, total_count
            return [deserialize_run(doc.get("run_type"), doc["run_data"]) for doc in run_rows]
        except Exception as e:
            log_error(f"Exception reading from runs collection: {str(e)}")
            raise e

    def _scrub_run_ids_from_legacy_blob(self, run_ids: List[str]) -> None:
        """Remove ``run_ids`` from every session document's legacy ``runs``
        array. Prevents ghost re-appearance during partial-migration state
        via the merge helper (see ``JsonDb`` for the pattern)."""
        if not run_ids:
            return
        try:
            sessions = self._get_collection(table_type="sessions")
            if sessions is None:
                return
            sessions.update_many(
                {"runs.run_id": {"$in": list(run_ids)}},
                {"$pull": {"runs": {"run_id": {"$in": list(run_ids)}}}},
            )
        except Exception:
            # Legacy blob scrub is best-effort — a failure here shouldn't
            # rollback the primary runs-collection delete.
            log_debug("legacy-runs scrub failed; the primary delete still succeeded", exc_info=True)

    def delete_run(self, run_id: str) -> bool:
        """Delete a single run from the runs collection."""
        try:
            collection = self._get_collection(table_type="runs")
            if collection is None:
                return False
            result = collection.delete_one({"run_id": run_id})
            self._scrub_run_ids_from_legacy_blob([run_id])
            return result.deleted_count > 0
        except Exception as e:
            log_error(f"Error deleting run: {str(e)}")
            raise e

    def delete_runs(self, run_ids: List[str]) -> None:
        """Delete all given runs from the runs collection."""
        try:
            collection = self._get_collection(table_type="runs")
            if collection is None:
                return
            result = collection.delete_many({"run_id": {"$in": run_ids}})
            self._scrub_run_ids_from_legacy_blob(run_ids)
            log_debug(f"Successfully deleted {result.deleted_count} runs")
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
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return False
            runs_collection = self._get_collection(table_type="runs", create_collection_if_not_found=True)

            query: Dict[str, Any] = {"session_id": session_id}
            if user_id is not None:
                query["user_id"] = user_id
            result = collection.delete_one(query)
            if result.deleted_count == 0:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False

            # Cascade-delete the session's runs
            if runs_collection is not None:
                runs_collection.delete_many({"session_id": session_id})

            log_debug(f"Successfully deleted session with session_id: {session_id}")
            return True

        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from the database.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
        """
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return
            runs_collection = self._get_collection(table_type="runs", create_collection_if_not_found=True)

            query: Dict[str, Any] = {"session_id": {"$in": session_ids}}
            if user_id is not None:
                query["user_id"] = user_id
            result = collection.delete_many(query)

            if runs_collection is not None:
                runs_query: Dict[str, Any] = {"session_id": {"$in": session_ids}}
                if user_id is not None:
                    runs_query["user_id"] = user_id
                runs_collection.delete_many(runs_query)

            log_debug(f"Successfully deleted {result.deleted_count} sessions")

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
            session_type (Optional[SessionType]): The type of session to get. If None, auto-detected from record.
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
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return None
            runs_collection = self._get_collection(table_type="runs", create_collection_if_not_found=True)

            query = {"session_id": session_id}
            if user_id is not None:
                query["user_id"] = user_id

            result = collection.find_one(query)
            if result is None:
                return None

            session = deserialize_session_json_fields(result)

            # Attach the runs stored in the runs collection, merged with any runs still
            # sitting in the legacy `runs` field (so partially-migrated sessions don't
            # silently lose history).
            legacy_runs = session.get("runs")
            if runs_collection is not None and runs_limit is not None and not legacy_runs:
                # Fully migrated: push "most recent N" down to the DB (indexed).
                session["runs"] = self._get_session_runs_docs(runs_collection, session_id, limit=runs_limit)
            elif runs_collection is not None:
                # Full load + merge. Also the un-migrated fallback: the legacy blob
                # holds the whole history in one field, so "last N" can't be pushed
                # to the DB — load all, merge, then filter+slice to match the migrated path.
                runs_data = self._get_session_runs_docs(runs_collection, session_id)
                merged = merge_runs_table_with_legacy_blob(runs_data, legacy_runs)
                if runs_limit is not None:
                    merged = filter_context_runs(merged)[-runs_limit:]
                session["runs"] = merged
            elif runs_limit is not None:
                # No runs collection yet (fully un-migrated): filter+slice the legacy blob.
                merged = merge_runs_table_with_legacy_blob([], legacy_runs)
                session["runs"] = filter_context_runs(merged)[-runs_limit:]

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
        filter_expr: Optional[Dict[str, Any]] = None,
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
            create_table_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Union[List[AgentSession], List[TeamSession], List[WorkflowSession], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of Session objects
                - When deserialize=False: List of session dictionaries and the total count

        Raises:
            Exception: If there is an error reading the sessions.
        """
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return [] if deserialize else ([], 0)
            runs_collection = self._get_collection(table_type="runs", create_collection_if_not_found=True)

            # Filtering
            query: Dict[str, Any] = {}
            if user_id is not None:
                query["user_id"] = user_id
            if session_type is not None:
                query["session_type"] = session_type.value if hasattr(session_type, "value") else session_type
            if component_id is not None:
                if session_type == SessionType.AGENT:
                    query["agent_id"] = component_id
                elif session_type == SessionType.TEAM:
                    query["team_id"] = component_id
                elif session_type == SessionType.WORKFLOW:
                    query["workflow_id"] = component_id
                elif session_type is None:
                    query["$or"] = [
                        {"agent_id": component_id},
                        {"team_id": component_id},
                        {"workflow_id": component_id},
                    ]
            if start_timestamp is not None:
                query["created_at"] = {"$gte": start_timestamp}
            if end_timestamp is not None:
                if "created_at" in query:
                    query["created_at"]["$lte"] = end_timestamp
                else:
                    query["created_at"] = {"$lte": end_timestamp}
            if session_name is not None:
                query["session_data.session_name"] = {"$regex": re.escape(session_name), "$options": "i"}

            if filter_expr is not None:
                from agno.db.session_filters import normalize_session_filter, session_filter_to_mongo

                expression = normalize_session_filter(filter_expr)
                if expression is not None:
                    advanced = session_filter_to_mongo(expression)
                    query = {"$and": [query, advanced]} if query else advanced

            # Get total count
            total_count = collection.count_documents(query)

            cursor = collection.find(query)

            # Sorting
            sort_criteria = apply_sorting({}, sort_by, sort_order)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)

            # Pagination
            query_args = apply_pagination({}, limit, page)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            records = list(cursor)
            if records is None:
                return [] if deserialize else ([], 0)
            sessions_raw = [deserialize_session_json_fields(record) for record in records]

            # Attach runs from the runs collection, merged with any runs still sitting
            # in the legacy `runs` field.
            if runs_collection is not None and sessions_raw:
                runs_by_session = self._get_sessions_runs_docs(runs_collection, [s["session_id"] for s in sessions_raw])
                for s in sessions_raw:
                    runs_data = runs_by_session.get(s["session_id"], [])
                    s["runs"] = merge_runs_table_with_legacy_blob(runs_data, s.get("runs"))

            if not deserialize:
                return sessions_raw, total_count

            return deserialize_sessions(session_type, sessions_raw)

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
            session_type (Optional[SessionType]): The type of session to rename.
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
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return None
            runs_collection = self._get_collection(table_type="runs", create_collection_if_not_found=True)

            query: Dict[str, Any] = {"session_id": session_id}
            if user_id is not None:
                query["user_id"] = user_id
            if session_type is not None:
                query["session_type"] = session_type.value
            try:
                result = collection.find_one_and_update(
                    query,
                    {"$set": {"session_data.session_name": session_name, "updated_at": int(time.time())}},
                    return_document=ReturnDocument.AFTER,
                    upsert=False,
                )
            except OperationFailure:
                # If the update fails because session_data doesn't contain a session_name yet, we initialize session_data
                result = collection.find_one_and_update(
                    query,
                    {"$set": {"session_data": {"session_name": session_name}, "updated_at": int(time.time())}},
                    return_document=ReturnDocument.AFTER,
                    upsert=False,
                )
            if not result:
                return None

            deserialized_session = deserialize_session_json_fields(result)

            if runs_collection is not None:
                runs_data = self._get_session_runs_docs(runs_collection, session_id)
                deserialized_session["runs"] = merge_runs_table_with_legacy_blob(
                    runs_data, deserialized_session.get("runs")
                )

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
            collection = self._get_collection(table_type="sessions", create_collection_if_not_found=True)
            if collection is None:
                return None

            session_dict = session.to_dict(include_runs=False)

            existing = collection.find_one({"session_id": session_dict.get("session_id")}, {"user_id": 1, "runs": 1})
            if existing:
                existing_uid = existing.get("user_id")
                if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                    return None

            incoming_uid = session_dict.get("user_id")
            upsert_filter: Dict[str, Any] = {"session_id": session_dict.get("session_id")}
            if incoming_uid is not None:
                upsert_filter["$or"] = [{"user_id": incoming_uid}, {"user_id": None}, {"user_id": {"$exists": False}}]
            else:
                upsert_filter["$or"] = [{"user_id": None}, {"user_id": {"$exists": False}}]

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

            # Preserve the legacy `runs` field as a frozen backup. find_one_and_replace
            # replaces the whole document, so carry any existing legacy blob forward; runs
            # now live in their own collection and only cleanup_legacy_runs_field() reclaims
            # it. Dropping it here would lose history for sessions not yet migrated.
            if existing and existing.get("runs") is not None:
                record["runs"] = existing["runs"]

            try:
                result = collection.find_one_and_replace(
                    filter=upsert_filter,
                    replacement=record,
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
            except DuplicateKeyError:
                return None
            if not result:
                return None

            # Attach the in-memory runs to the returned dict so callers see the full picture
            result["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]

            if not deserialize:
                return result

            return deserialize_session(None, result)

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
            preserve_updated_at (bool): If True, preserve the updated_at from the session object.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not sessions:
            return []

        try:
            collection = self._get_collection(table_type="sessions", create_collection_if_not_found=True)
            if collection is None:
                log_info("Sessions collection not available, falling back to individual upserts")
                return [
                    result
                    for session in sessions
                    if session is not None
                    for result in [self.upsert_session(session, deserialize=deserialize)]
                    if result is not None
                ]
            from pymongo import ReplaceOne

            operations = []
            results: List[Union[Session, Dict[str, Any]]] = []

            sessions_by_id: Dict[str, Session] = {s.session_id: s for s in sessions if s is not None}

            # Preserve the legacy `runs` field as a frozen backup. ReplaceOne replaces the
            # whole document, so fetch any existing legacy blobs up front and carry them
            # forward; only cleanup_legacy_runs_field() reclaims them. Dropping them here
            # would lose history for sessions not yet migrated to the runs collection.
            legacy_runs_by_id: Dict[str, Any] = {}
            if sessions_by_id:
                for doc in collection.find(
                    {"session_id": {"$in": list(sessions_by_id.keys())}}, {"session_id": 1, "runs": 1}
                ):
                    if doc.get("runs") is not None:
                        legacy_runs_by_id[doc["session_id"]] = doc["runs"]

            for session in sessions:
                if session is None:
                    continue

                session_dict = session.to_dict(include_runs=False)

                # Use preserved updated_at if flag is set and value exists, otherwise use current time
                updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())

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
                        "updated_at": updated_at,
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
                        "updated_at": updated_at,
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
                        "updated_at": updated_at,
                    }
                else:
                    continue

                legacy_runs = legacy_runs_by_id.get(session.session_id)
                if legacy_runs is not None:
                    record["runs"] = legacy_runs

                operations.append(
                    ReplaceOne(filter={"session_id": record["session_id"]}, replacement=record, upsert=True)
                )

            if operations:
                # Execute bulk write
                collection.bulk_write(operations)

                # Fetch the results
                session_ids = [session.session_id for session in sessions if session and session.session_id]
                cursor = collection.find({"session_id": {"$in": session_ids}})

                for doc in cursor:
                    session_dict = doc
                    # Attach the in-memory runs for callers
                    original_session = sessions_by_id.get(doc.get("session_id"))
                    session_dict["runs"] = [
                        run if isinstance(run, dict) else run.to_dict()
                        for run in (original_session.runs if original_session else None) or []
                    ]

                    if deserialize:
                        session_type = doc.get("session_type")
                        if session_type == SessionType.AGENT.value:
                            deserialized_agent_session = AgentSession.from_dict(session_dict)
                            if deserialized_agent_session is None:
                                continue
                            results.append(deserialized_agent_session)

                        elif session_type == SessionType.TEAM.value:
                            deserialized_team_session = TeamSession.from_dict(session_dict)
                            if deserialized_team_session is None:
                                continue
                            results.append(deserialized_team_session)

                        elif session_type == SessionType.WORKFLOW.value:
                            deserialized_workflow_session = WorkflowSession.from_dict(session_dict)
                            if deserialized_workflow_session is None:
                                continue
                            results.append(deserialized_workflow_session)
                    else:
                        results.append(session_dict)

            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert, falling back to individual upserts: {str(e)}")

            # Fallback to individual upserts
            return [
                result
                for session in sessions
                if session is not None
                for result in [self.upsert_session(session, deserialize=deserialize)]
                if result is not None
            ]

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user to verify ownership. If provided, only delete if the memory belongs to this user.

        Returns:
            bool: True if the memory was deleted, False otherwise.

        Raises:
            Exception: If there is an error deleting the memory.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return

            query = {"memory_id": memory_id}
            if user_id is not None:
                query["user_id"] = user_id

            result = collection.delete_one(query)

            success = result.deleted_count > 0
            if success:
                log_debug(f"Successfully deleted memory id: {memory_id}")
            else:
                log_debug(f"No memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting memory: {str(e)}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user to verify ownership. If provided, only delete memories that belong to this user.

        Raises:
            Exception: If there is an error deleting the memories.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return

            query: Dict[str, Any] = {"memory_id": {"$in": memory_ids}}
            if user_id is not None:
                query["user_id"] = user_id

            result = collection.delete_many(query)

            if result.deleted_count == 0:
                log_debug(f"No memories found with ids: {memory_ids}")

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
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return []

            match_filter: Dict[str, Any] = {} if user_id is None else {"user_id": user_id}
            topics = collection.distinct("topics", match_filter)
            return [topic for topic in topics if topic]

        except Exception as e:
            log_error(f"Exception reading from collection: {str(e)}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[UserMemory]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user to verify ownership. If provided, only return the memory if it belongs to this user.

        Returns:
            Optional[UserMemory]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If there is an error getting the memory.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return None

            query = {"memory_id": memory_id}
            if user_id is not None:
                query["user_id"] = user_id

            result = collection.find_one(query)
            if result is None or not deserialize:
                return result

            # Remove MongoDB's _id field before creating UserMemory object
            result_filtered = {k: v for k, v in result.items() if k != "_id"}
            return UserMemory.from_dict(result_filtered)

        except Exception as e:
            log_error(f"Exception reading from collection: {str(e)}")
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
            create_table_if_not_found: Whether to create the collection if it doesn't exist.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the memories and the total count.

        Raises:
            Exception: If there is an error getting the memories.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return [] if deserialize else ([], 0)

            query: Dict[str, Any] = {}
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if topics is not None:
                query["topics"] = {"$in": topics}
            if search_content is not None:
                query["memory"] = {"$regex": re.escape(search_content), "$options": "i"}

            # Get total count
            total_count = collection.count_documents(query)

            # Apply sorting
            sort_criteria = apply_sorting({}, sort_by, sort_order)

            # Apply pagination
            query_args = apply_pagination({}, limit, page)

            cursor = collection.find(query)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            records = list(cursor)
            if not deserialize:
                return records, total_count

            # Remove MongoDB's _id field before creating UserMemory objects
            return [UserMemory.from_dict({k: v for k, v in record.items() if k != "_id"}) for record in records]

        except Exception as e:
            log_error(f"Exception reading from collection: {str(e)}")
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
            user_id (Optional[str]): User ID for filtering.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the memories stats and the total count.

        Raises:
            Exception: If there is an error getting the memories stats.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return [], 0

            match_stage: Dict[str, Any] = {"user_id": {"$ne": None}}
            if user_id is not None:
                match_stage["user_id"] = user_id

            pipeline: List[Dict[str, Any]] = [
                {"$match": match_stage},
                {
                    "$group": {
                        "_id": "$user_id",
                        "total_memories": {"$sum": 1},
                        "last_memory_updated_at": {"$max": "$updated_at"},
                    }
                },
                {"$sort": {"last_memory_updated_at": -1}},
            ]

            # Get total count
            count_pipeline = pipeline + [{"$count": "total"}]
            count_result = list(collection.aggregate(count_pipeline))  # type: ignore
            total_count = count_result[0]["total"] if count_result else 0

            # Apply pagination
            if limit is not None:
                if page is not None:
                    pipeline.append({"$skip": (page - 1) * limit})
                pipeline.append({"$limit": limit})

            results = list(collection.aggregate(pipeline))  # type: ignore

            formatted_results = [
                {
                    "user_id": result["_id"],
                    "total_memories": result["total_memories"],
                    "last_memory_updated_at": result["last_memory_updated_at"],
                }
                for result in results
            ]

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
            collection = self._get_collection(table_type="memories", create_collection_if_not_found=True)
            if collection is None:
                return None

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            update_doc = {
                "user_id": memory.user_id,
                "agent_id": memory.agent_id,
                "team_id": memory.team_id,
                "memory_id": memory.memory_id,
                "memory": memory.memory,
                "topics": memory.topics,
                "updated_at": int(time.time()),
            }

            result = collection.replace_one({"memory_id": memory.memory_id}, update_doc, upsert=True)

            if result.upserted_id:
                update_doc["_id"] = result.upserted_id

            if not deserialize:
                return update_doc

            # Remove MongoDB's _id field before creating UserMemory object
            update_doc_filtered = {k: v for k, v in update_doc.items() if k != "_id"}
            return UserMemory.from_dict(update_doc_filtered)

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
            collection = self._get_collection(table_type="memories", create_collection_if_not_found=True)
            if collection is None:
                log_info("Memories collection not available, falling back to individual upserts")
                return [
                    result
                    for memory in memories
                    if memory is not None
                    for result in [self.upsert_user_memory(memory, deserialize=deserialize)]
                    if result is not None
                ]

            from pymongo import ReplaceOne

            operations = []
            results: List[Union[UserMemory, Dict[str, Any]]] = []

            current_time = int(time.time())
            for memory in memories:
                if memory is None:
                    continue

                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                # Use preserved updated_at if flag is set and value exists, otherwise use current time
                updated_at = memory.updated_at if preserve_updated_at else current_time

                record = {
                    "user_id": memory.user_id,
                    "agent_id": memory.agent_id,
                    "team_id": memory.team_id,
                    "memory_id": memory.memory_id,
                    "memory": memory.memory,
                    "input": memory.input,
                    "feedback": memory.feedback,
                    "topics": memory.topics,
                    "created_at": memory.created_at,
                    "updated_at": updated_at,
                }

                operations.append(ReplaceOne(filter={"memory_id": memory.memory_id}, replacement=record, upsert=True))

            if operations:
                # Execute bulk write
                collection.bulk_write(operations)

                # Fetch the results
                memory_ids = [memory.memory_id for memory in memories if memory and memory.memory_id]
                cursor = collection.find({"memory_id": {"$in": memory_ids}})

                for doc in cursor:
                    if deserialize:
                        # Remove MongoDB's _id field before creating UserMemory object
                        doc_filtered = {k: v for k, v in doc.items() if k != "_id"}
                        results.append(UserMemory.from_dict(doc_filtered))
                    else:
                        results.append(doc)

            return results

        except Exception as e:
            log_error(f"Exception during bulk memory upsert, falling back to individual upserts: {str(e)}")

            # Fallback to individual upserts
            return [
                result
                for memory in memories
                if memory is not None
                for result in [self.upsert_user_memory(memory, deserialize=deserialize)]
                if result is not None
            ]

    def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return

            collection.delete_many({})

        except Exception as e:
            log_error(f"Exception deleting all memories: {str(e)}")
            raise e

    # -- Metrics methods --

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions of all types for metrics calculation."""
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return []
            runs_collection = self._get_collection(table_type="runs", create_collection_if_not_found=True)

            query = {}
            if start_timestamp is not None:
                query["created_at"] = {"$gte": start_timestamp}
            if end_timestamp is not None:
                if "created_at" in query:
                    query["created_at"]["$lte"] = end_timestamp
                else:
                    query["created_at"] = {"$lte": end_timestamp}

            projection = {
                "session_id": 1,
                "user_id": 1,
                "session_data": 1,
                "runs": 1,  # the legacy field — for un-migrated sessions
                "created_at": 1,
                "session_type": 1,
            }

            sessions = list(collection.find(query, projection))

            # Attach lightweight run info (model + provider) from the runs collection.
            # calculate_date_metrics only needs len(runs) and run["model"] / run["model_provider"].
            if runs_collection is not None and sessions:
                session_ids = [s["session_id"] for s in sessions]
                runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
                for doc in runs_collection.find(
                    {"session_id": {"$in": session_ids}},
                    {"session_id": 1, "run_data.model": 1, "run_data.model_provider": 1},
                ):
                    run_data = doc.get("run_data") or {}
                    runs_by_session.setdefault(doc["session_id"], []).append(
                        {"model": run_data.get("model"), "model_provider": run_data.get("model_provider")}
                    )

                for s in sessions:
                    rb = runs_by_session.get(s["session_id"], [])
                    if rb or not s.get("runs"):
                        s["runs"] = rb

            return sessions

        except Exception as e:
            log_error(f"Exception reading from sessions collection: {str(e)}")
            return []

    def _get_metrics_calculation_starting_date(self, collection: Collection) -> Optional[date]:
        """Get the first date for which metrics calculation is needed."""
        try:
            # resume at the earliest incomplete day after the latest completed one, otherwise the day after
            # that one (:func:`metrics_starting_date_from_days`): the dates are ISO strings, so both queries order
            # lexicographically and the collection is never loaded whole
            completed_record = collection.find_one({"completed": True}, sort=[("date", -1)])
            latest_completed = completed_record["date"] if completed_record else None

            incomplete_filter: Dict[str, Any] = {"completed": {"$ne": True}}
            if latest_completed is not None:
                incomplete_filter["date"] = {"$gt": latest_completed}
            earliest_incomplete = collection.find_one(incomplete_filter, sort=[("date", 1)])

            starting_date = metrics_starting_date_from_days(
                datetime.strptime(latest_completed, "%Y-%m-%d").date() if latest_completed is not None else None,
                datetime.strptime(earliest_incomplete["date"], "%Y-%m-%d").date()
                if earliest_incomplete is not None
                else None,
            )
            if starting_date is not None:
                return starting_date

            # No metrics records. Return the date of the first recorded session.
            first_session_result = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
            first_session_date = first_session_result[0][0]["created_at"] if first_session_result[0] else None  # type: ignore

            if first_session_date is None:
                return None

            return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

        except Exception as e:
            log_error(f"Exception getting metrics calculation starting date: {str(e)}")
            return None

    def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics."""
        try:
            collection = self._get_collection(table_type="metrics", create_collection_if_not_found=True)
            if collection is None:
                return None

            starting_date = self._get_metrics_calculation_starting_date(collection)
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
            metrics_records = []

            for date_to_process in dates_to_process:
                date_key = date_to_process.isoformat()
                sessions_for_date = all_sessions_data.get(date_key, {})

                # Skip dates with no sessions
                if not any(len(sessions) > 0 for sessions in sessions_for_date.values()):
                    continue

                # One record per distinct user_id, plus an empty-string bucket for unowned sessions
                metrics_records.extend(calculate_date_metrics(date_to_process, sessions_for_date))

            if metrics_records:
                results = bulk_upsert_metrics(collection, metrics_records)

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
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.
            user_id (Optional[str]): Return only this user's bucket. ``None`` returns every bucket.
        """
        try:
            collection = self._get_collection(table_type="metrics")
            if collection is None:
                return [], None

            query: Dict[str, Any] = {}
            if starting_date:
                query["date"] = {"$gte": starting_date.isoformat()}
            if ending_date:
                if "date" in query:
                    query["date"]["$lte"] = ending_date.isoformat()
                else:
                    query["date"] = {"$lte": ending_date.isoformat()}
            if user_id is not None:
                query["user_id"] = user_id

            records = list(collection.find(query))
            # Records written before ownership existed hold a whole day, and only an
            # unscoped read sees them: an owner filter excludes them already
            if user_id is None:
                records = drop_legacy_metrics(records)
            if not records:
                return [], None

            # Get the latest updated_at
            latest_updated_at = max(record.get("updated_at", 0) for record in records)

            # Map the empty-string user_id sentinel back to None, and drop MongoDB's _id field
            cleaned: List[dict] = []
            for record in records:
                row = dict(record)
                row.pop("_id", None)
                if row.get("user_id") == "":
                    row["user_id"] = None
                cleaned.append(row)
            return cleaned, latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics: {str(e)}")
            raise e

    # -- OS metrics methods --

    def _get_os_metrics_calculation_starting_date(self, totals_collection: Collection) -> Optional[date]:
        """Get the first date for which OS metrics calculation is needed:

        1. If there are total rows of days, return the earliest day not completed after the latest completed one,
           otherwise the day after that one.
        2. If there are none, return the date of the first recorded session.
        3. If there are no total rows and no sessions records, return None.

        Args:
            totals_collection (Collection): The OS metrics totals collection.

        Returns:
            Optional[date]: The starting date for which OS metrics calculation is needed.
        """
        # resume at the earliest incomplete day after the latest completed one, otherwise the day after
        # that one: the dates are ISO strings, so both queries order lexicographically
        completed_record = totals_collection.find_one(
            {"aggregation_period": "daily", "completed": True}, {"date": 1}, sort=[("date", -1)]
        )
        latest_completed = completed_record["date"] if completed_record else None

        incomplete_filter: Dict[str, Any] = {"aggregation_period": "daily", "completed": False}
        if latest_completed is not None:
            incomplete_filter["date"] = {"$gt": latest_completed}
        earliest_incomplete = totals_collection.find_one(incomplete_filter, {"date": 1}, sort=[("date", 1)])

        starting_date = metrics_starting_date_from_days(
            datetime.strptime(latest_completed, "%Y-%m-%d").date() if latest_completed is not None else None,
            datetime.strptime(earliest_incomplete["date"], "%Y-%m-%d").date()
            if earliest_incomplete is not None
            else None,
        )
        if starting_date is not None:
            return starting_date

        # No total rows. Return the date of the first recorded session.
        # Queried directly rather than through get_sessions, which also counts every session and loads runs
        sessions_collection = self._get_collection(table_type="sessions")
        if sessions_collection is None:
            return None
        first_session = sessions_collection.find_one(
            {"created_at": {"$ne": None}}, {"created_at": 1}, sort=[("created_at", 1)]
        )
        first_session_date = first_session["created_at"] if first_session else None

        if first_session_date is None:
            return None

        return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

    def _calculate_month_os_metrics(
        self, collection: Collection, totals_collection: Collection, wait_for_rebuild: bool
    ) -> List[Dict[str, Any]]:
        """Calculate the month rows of every completed month that has none.

        A completed month gets its month rows once, whichever rebuild completed its days. They are written
        after the days, so a month that fails to calculate never holds back the rows of a day.

        Args:
            collection (Collection): The OS metrics collection.
            totals_collection (Collection): The OS metrics totals collection.
            wait_for_rebuild (bool): Wait for a rebuild another process is running. When False, skip instead.

        Returns:
            List[Dict[str, Any]]: The total rows of the months written.
        """
        results: List[Dict[str, Any]] = []
        # Under the days' lock, so a month is written by one rebuild only
        rebuild_id = str(uuid4())
        if not lock_os_metrics(collection, rebuild_id, wait_for_rebuild):
            return results
        try:
            total_rows = [
                deserialize_os_metrics_row(document)
                for document in totals_collection.find(
                    {"aggregation_period": {"$in": ["daily", "monthly"]}},
                    {"aggregation_period": 1, "date": 1, "completed": 1},
                )
            ]
            day_starts = [record["date"] for record in total_rows if record["aggregation_period"] == "daily"]
            calculated_months = [record["date"] for record in total_rows if record["aggregation_period"] == "monthly"]
            latest_completed = max(
                (
                    record["date"]
                    for record in total_rows
                    if record["aggregation_period"] == "daily" and record.get("completed")
                ),
                default=None,
            )
            for month_start in get_months_to_calculate_os_metrics_for(day_starts, calculated_months, latest_completed):
                # Server-side cursor, so a month of many rows is added up a batch at a time instead of held whole
                cursor = collection.find(
                    {
                        "aggregation_period": "daily",
                        "date": {
                            "$gte": month_start.isoformat(),
                            "$lte": os_metrics_month_end(month_start).isoformat(),
                        },
                    },
                    {"_id": False},
                ).batch_size(OS_METRICS_BATCH_SIZE)
                per_owner: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
                batch: List[Dict[str, Any]] = []
                for document in cursor:
                    batch.append(deserialize_os_metrics_row(document))
                    if len(batch) >= OS_METRICS_BATCH_SIZE:
                        add_month_os_metrics(per_owner, batch)
                        batch = []
                if batch:
                    add_month_os_metrics(per_owner, batch)

                month_rows = calculate_month_os_metrics(month_start, per_owner)
                # A rebuild that lost the lock stops, so a month is written by one rebuild only
                if not extend_os_metrics_lock(collection, rebuild_id):
                    return results
                bulk_upsert_os_metrics(collection, month_rows)
                # Written last: a read takes a month from its rows only once the month has a total row
                totals_row = build_os_metrics_totals_row(month_rows, "monthly", month_start, completed=True)
                upsert_os_metrics_totals_row(totals_collection, totals_row)
                results.append(totals_row)
        finally:
            unlock_os_metrics(collection, rebuild_id)

        return results

    def _get_os_metrics_legacy_runs(
        self, runs_collection: Optional[Collection], sessions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get the runs of the given sessions' legacy runs field that the runs collection does not hold."""
        legacy_runs = get_os_metrics_legacy_runs(sessions)
        if runs_collection is None:
            return legacy_runs

        # The runs collection wins on a run in both, as merge_runs_table_with_legacy_blob does
        legacy_run_ids = [run["run_id"] for run in legacy_runs]
        migrated_run_ids: Set[str] = set()
        for start in range(0, len(legacy_run_ids), OS_METRICS_IN_LIST_LIMIT):
            migrated_run_ids.update(
                document["run_id"]
                for document in runs_collection.find(
                    {"run_id": {"$in": legacy_run_ids[start : start + OS_METRICS_IN_LIST_LIMIT]}},
                    {"run_id": 1, "_id": False},
                )
            )
        return [run for run in legacy_runs if run["run_id"] not in migrated_run_ids]

    def _get_os_metrics_fingerprint(
        self, sessions_collection: Collection, runs_collection: Optional[Collection], dates_to_process: List[date]
    ) -> Optional[Tuple[Any, ...]]:
        """Get the count and update times of the sessions and runs of the given dates. None while one of them was
        updated in the current second, which a second update in that same second would leave unchanged."""
        start_timestamp = int(
            datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
        )
        current_time = int(time.time())
        fingerprint: List[Any] = [dates_to_process[0], dates_to_process[-1]]
        for source_collection in [sessions_collection, runs_collection]:
            if source_collection is None:
                continue
            result = list(
                source_collection.aggregate(
                    [
                        {"$match": {"created_at": {"$gte": start_timestamp}}},
                        {
                            "$group": {
                                "_id": None,
                                "count": {"$sum": 1},
                                "total_updated_at": {"$sum": "$updated_at"},
                                "latest_updated_at": {"$max": "$updated_at"},
                            }
                        },
                    ]
                )
            )
            count = result[0]["count"] if result else 0
            total_updated_at = result[0]["total_updated_at"] if result else None
            latest_updated_at = result[0]["latest_updated_at"] if result else None
            if latest_updated_at is not None and latest_updated_at >= current_time:
                return None
            fingerprint.extend([count, total_updated_at])
        return tuple(fingerprint)

    def _calculate_os_metrics(
        self, wait_for_rebuild: bool
    ) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
        """Calculate OS metrics for all dates without complete OS metrics.

        Args:
            wait_for_rebuild (bool): Wait for a rebuild another process is running. When False, skip instead.

        Returns:
            Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]: The calculated OS metrics and the total
                rows written.

        Raises:
            Exception: If an error occurs during OS metrics calculation.
        """
        # Stamp first so failed runs are throttled too instead of retried on every read
        self._os_metrics_refreshed_at = time.time()

        collection = self._get_collection(table_type="os_metrics", create_collection_if_not_found=True)
        totals_collection = self._get_collection(table_type="os_metrics_totals", create_collection_if_not_found=True)
        if collection is None or totals_collection is None:
            return None

        starting_date = self._get_os_metrics_calculation_starting_date(totals_collection)

        if starting_date is None:
            log_info("No session data found. Won't calculate OS metrics.")
            return None

        # Yesterday is never completed, so it is rebuilt even when it has no total row yet: a run that started
        # before midnight and was stored after it is dated yesterday
        starting_date = min(starting_date, datetime.now(timezone.utc).date() - timedelta(days=1))

        dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
        if not dates_to_process:
            log_info("OS metrics already calculated for all relevant dates.")
            return None

        sessions_collection = self._get_collection(table_type="sessions")
        if sessions_collection is None:
            return None
        runs_collection = self._get_collection(table_type="runs", create_collection_if_not_found=True)

        # Read before the days, so a session or run written while they are rebuilt moves the next one
        fingerprint = self._get_os_metrics_fingerprint(sessions_collection, runs_collection, dates_to_process)
        if not wait_for_rebuild and fingerprint is not None and fingerprint == self._os_metrics_fingerprint:
            return None

        # Runs not yet migrated out of the legacy runs field, dated as the v3.0.0 migration dates them. A session
        # holds the runs created after it started and before it was last written
        rebuild_start = int(
            datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
        )
        rebuild_end = int(
            datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        # Read a batch at a time, so only the runs not yet migrated are held, never every legacy runs field
        cursor = sessions_collection.find(
            {
                "created_at": {"$lt": rebuild_end},
                "runs": {"$ne": None},
                "$or": [
                    {"updated_at": {"$gte": rebuild_start}},
                    {"updated_at": None, "created_at": {"$gte": rebuild_start}},
                ],
            },
            {"user_id": 1, "created_at": 1, "runs": 1},
        ).batch_size(OS_METRICS_BATCH_SIZE)
        legacy_runs: List[Dict[str, Any]] = []
        batch: List[Dict[str, Any]] = []
        for session in cursor:
            batch.append(session)
            if len(batch) >= OS_METRICS_BATCH_SIZE:
                legacy_runs.extend(self._get_os_metrics_legacy_runs(runs_collection, batch))
                batch = []
        if batch:
            legacy_runs.extend(self._get_os_metrics_legacy_runs(runs_collection, batch))
        legacy_runs_by_day = get_os_metrics_records_by_day(legacy_runs, rebuild_start, rebuild_end)
        legacy_runs_by_id = {run["run_id"]: run for run in legacy_runs}

        results: List[Dict[str, Any]] = []
        written_totals_rows: List[Dict[str, Any]] = []
        rebuild_id = str(uuid4())

        for date_to_process in dates_to_process:
            # One rebuild of this collection at a time: a second one waits here, or skips when told not to wait.
            # The lock is released once the day is written
            if not lock_os_metrics(collection, rebuild_id, wait_for_rebuild):
                # Reset the throttle so the next read tries again
                self._os_metrics_refreshed_at = 0.0
                log_info("Another process is calculating OS metrics. Won't calculate OS metrics.")
                return None
            try:
                date_key = date_to_process.isoformat()

                # Skip a day a rebuild this one waited for has completed
                completed_record = totals_collection.find_one(
                    {"aggregation_period": "daily", "completed": True}, {"date": 1}, sort=[("date", -1)]
                )
                if completed_record is not None and date_key <= completed_record["date"]:
                    continue

                start_timestamp = int(
                    datetime.combine(date_to_process, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
                )
                end_timestamp = int(
                    datetime.combine(date_to_process + timedelta(days=1), datetime.min.time())
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )

                sessions = list(
                    sessions_collection.find(
                        {"created_at": {"$gte": start_timestamp, "$lt": end_timestamp}},
                        {"session_type": 1, "user_id": 1, "agent_id": 1, "team_id": 1, "workflow_id": 1},
                    )
                )

                runs: List[Dict[str, Any]] = []
                stored_run_ids: Set[str] = set()
                legacy_runs = legacy_runs_by_day.get(date_to_process, [])
                if runs_collection is not None:
                    runs = list(
                        runs_collection.find(
                            {"created_at": {"$gte": start_timestamp, "$lt": end_timestamp}},
                            build_os_metrics_runs_projection(),
                        )
                    )

                    # A nested run also stored as a run of its own is counted from that document, whatever day it is on
                    run_ids = sorted(os_metrics_nested_run_ids(runs + legacy_runs))
                    for start in range(0, len(run_ids), OS_METRICS_IN_LIST_LIMIT):
                        stored_run_ids.update(
                            document["run_id"]
                            for document in runs_collection.find(
                                {"run_id": {"$in": run_ids[start : start + OS_METRICS_IN_LIST_LIMIT]}},
                                # Only run_id, so the run_id index answers the query without reading the documents
                                {"run_id": 1, "_id": False},
                            )
                        )
                    # A legacy run migrated since the legacy runs were read is counted from the runs read above
                    collection_run_ids = {run["run_id"] for run in runs}
                    legacy_runs = [run for run in legacy_runs if run["run_id"] not in collection_run_ids]
                runs.extend(legacy_runs)

                # A run started by a run of another day, such as a member run after midnight, names that run's
                # agent, team or workflow as its parent, read from the legacy runs of the rebuild or the runs collection
                day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
                parent_run_ids = sorted(
                    {run["parent_run_id"] for run in runs if run.get("parent_run_id")} - day_run_ids
                )
                parent_runs = [legacy_runs_by_id[run_id] for run_id in parent_run_ids if run_id in legacy_runs_by_id]
                parent_run_ids = [run_id for run_id in parent_run_ids if run_id not in legacy_runs_by_id]

                if runs_collection is not None:
                    for start in range(0, len(parent_run_ids), OS_METRICS_IN_LIST_LIMIT):
                        parent_runs.extend(
                            runs_collection.find(
                                {"run_id": {"$in": parent_run_ids[start : start + OS_METRICS_IN_LIST_LIMIT]}},
                                {
                                    "run_id": 1,
                                    "run_type": 1,
                                    "agent_id": 1,
                                    "team_id": 1,
                                    "workflow_id": 1,
                                    "_id": False,
                                },
                            )
                        )

                records = calculate_date_os_metrics(date_to_process, sessions, runs, stored_run_ids, parent_runs)
                stored_rows = [
                    deserialize_os_metrics_row(document)
                    for document in collection.find({"aggregation_period": "daily", "date": date_key})
                ]

                changed_rows, stale_keys = os_metrics_rows_to_write(records, stored_rows)
                stored_ids = {
                    (row["user_id"], row["component_type"], row["component_id"], row["parent_component_id"]): row["_id"]
                    for row in stored_rows
                }
                stale_ids = [stored_ids[stale_key] for stale_key in stale_keys]
                # A rebuild that lost the lock stops: the process that holds it calculates the days left
                if not extend_os_metrics_lock(collection, rebuild_id):
                    log_info("Another process is calculating OS metrics. Won't calculate OS metrics.")
                    return results, written_totals_rows
                if changed_rows or stale_keys:
                    # No transaction spans a day, so a stopped rebuild leaves the next one to write the totals row
                    totals_collection.update_one(
                        {"aggregation_period": "daily", "date": date_key}, {"$set": {"rows_pending": True}}
                    )
                for start in range(0, len(stale_ids), OS_METRICS_IN_LIST_LIMIT):
                    collection.delete_many({"_id": {"$in": stale_ids[start : start + OS_METRICS_IN_LIST_LIMIT]}})
                bulk_upsert_os_metrics(collection, changed_rows)

                # Written last, so its version never moves before the rows it tells of
                stored_totals_row = totals_collection.find_one(
                    {"aggregation_period": "daily", "date": date_key}, {"_id": False}
                )
                totals_row = os_metrics_totals_row_to_write(
                    build_os_metrics_totals_row(
                        records, "daily", date_to_process, os_metrics_day_completed(date_to_process)
                    ),
                    deserialize_os_metrics_row(stored_totals_row) if stored_totals_row is not None else None,
                    rows_changed=bool(changed_rows or stale_keys or (stored_totals_row or {}).get("rows_pending")),
                )
                if totals_row is not None:
                    upsert_os_metrics_totals_row(totals_collection, totals_row)
                    written_totals_rows.append(totals_row)
                results.extend(records)
            finally:
                unlock_os_metrics(collection, rebuild_id)

        written_totals_rows.extend(self._calculate_month_os_metrics(collection, totals_collection, wait_for_rebuild))
        self._os_metrics_fingerprint = fingerprint

        log_debug("Updated OS metrics calculations")

        return results, written_totals_rows

    def _get_os_metrics_totals_by_date(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str],
        fields: List[str],
        use_month_rows: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Total the OS metrics of the given date range, every day from one period.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner.
            fields (List[str]): The fields to total.
            use_month_rows (bool): Total a calendar month inside the date range from its month rows, as one date.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each date, and when they were last updated.
        """
        totals_collection = self._get_collection(table_type="os_metrics_totals", create_collection_if_not_found=True)
        # Every owner is read from the total rows, one owner from that owner's rows
        collection = (
            totals_collection
            if user_id is None
            else self._get_collection(table_type="os_metrics", create_collection_if_not_found=True)
        )
        if totals_collection is None or collection is None:
            return [], None

        full_months = os_metrics_full_months(starting_date, ending_date) if use_month_rows else []
        month_starts: List[date] = []
        if full_months:
            # A month's total row is written after its rows, so a month that has one is read from its rows
            month_starts = [
                datetime.strptime(document["date"], "%Y-%m-%d").date()
                for document in totals_collection.find(
                    {
                        "aggregation_period": "monthly",
                        # The full months follow each other, so a range finds them however long the window is
                        "date": {"$gte": full_months[0].isoformat(), "$lte": full_months[-1].isoformat()},
                    },
                    {"date": 1},
                )
            ]
        # One aggregate, so every total of a document comes from one version of it. Without a replica set there
        # is no snapshot across documents: one owner's rows of a day being rewritten can be read half rewritten
        pipeline = build_os_metrics_totals_pipeline(
            starting_date, ending_date, user_id, fields, month_starts=month_starts
        )
        if not pipeline:
            return [], None
        return build_os_metrics_totals(fields, list(collection.aggregate(pipeline)))

    def calculate_os_metrics(self) -> Optional[List[Dict[str, Any]]]:
        """Calculate OS metrics for all dates without complete OS metrics.

        Returns:
            Optional[List[Dict[str, Any]]]: The calculated OS metrics.

        Raises:
            Exception: If an error occurs during OS metrics calculation.
        """
        try:
            calculation = self._calculate_os_metrics(wait_for_rebuild=True)
            if calculation is None:
                return None

            results, _ = calculation
            return results

        except Exception as e:
            log_error(f"Error calculating OS metrics: {str(e)}")
            raise e

    def refresh_os_metrics(self) -> Tuple[Optional[int], Optional[int], bool]:
        """Calculate OS metrics for all dates without complete OS metrics, and report whether any row changed.

        Returns:
            Tuple[Optional[int], Optional[int], bool]: When the OS metrics were last updated before the
                calculation and after it, and whether it wrote or deleted any row.

        Raises:
            Exception: If an error occurs during OS metrics calculation.
        """
        try:
            totals_collection = self._get_collection(
                table_type="os_metrics_totals", create_collection_if_not_found=True
            )
            if totals_collection is None:
                return None, None, False

            # A period's total row is written with every write of its rows, so the newest total row is the newest write
            previous_record = totals_collection.find_one({}, {"updated_at": 1}, sort=[("updated_at", -1)])
            previous_updated_at = previous_record.get("updated_at") if previous_record else None

            calculation = self._calculate_os_metrics(wait_for_rebuild=True)
            written_totals_rows: List[Dict[str, Any]] = []
            if calculation is not None:
                _, written_totals_rows = calculation

            latest_record = totals_collection.find_one({}, {"updated_at": 1}, sort=[("updated_at", -1)])
            latest_updated_at = latest_record.get("updated_at") if latest_record else None

            return previous_updated_at, latest_updated_at, bool(written_totals_rows)

        except Exception as e:
            log_error(f"Error calculating OS metrics: {str(e)}")
            raise e

    def get_os_metrics(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Get the OS metrics totals of each day in the given date range.

        OS metrics are refreshed lazily, at most once per minute per process, without waiting for a rebuild another
        process is running. For every owner, each day is read from its total row; for one owner, from its rows.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner.
            fields (Optional[List[str]]): The fields to total. ``None`` totals all.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each day, and when they were last updated.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            fields = resolve_os_metrics_fields(fields)

            # Refresh at most once per minute per process: recalculating the current
            # day scans all of today's sessions, too costly for every read.
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

        OS metrics are refreshed lazily, as in get_os_metrics. A calendar month inside the date range that has
        month rows is read from them, and every other day as get_os_metrics reads it.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner.
            fields (Optional[List[str]]): The fields to total. ``None`` totals all.

        Returns:
            Tuple[Dict[str, Any], Optional[int]]: The totals of the date range, and when they were last updated.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            fields = resolve_os_metrics_fields(fields)

            # Refresh at most once per minute per process: recalculating the current
            # day scans all of today's sessions, too costly for every read.
            if time.time() - self._os_metrics_refreshed_at >= 60:
                try:
                    self._calculate_os_metrics(wait_for_rebuild=False)
                except Exception as e:
                    log_warning(f"Could not refresh OS metrics before reading them: {str(e)}")

            totals, latest_updated_at = self._get_os_metrics_totals_by_date(
                starting_date, ending_date, user_id, fields, use_month_rows=True
            )
            return merge_os_metrics_totals(totals, fields), latest_updated_at

        except Exception as e:
            log_error(f"Error getting OS metrics totals: {str(e)}")
            raise e

    def get_os_metrics_versions(self, starting_date: date, ending_date: date) -> Optional[Dict[str, int]]:
        """Get the version of every total row of a day or a month in the given date range.

        OS metrics are refreshed lazily, as in get_os_metrics.

        Args:
            starting_date (date): The first day of the date range.
            ending_date (date): The last day of the date range.

        Returns:
            Optional[Dict[str, int]]: The version of each total row, keyed by its aggregation period and date. The
                same again only while no rebuild wrote or deleted a row of the date range. ``None`` while the days
                are not built up to today, which every rebuild writes last: a read would find them half built.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            # Refresh at most once per minute per process: recalculating the current
            # day scans all of today's sessions, too costly for every read. Refresh
            # again on a new UTC day, which has no total row until a refresh writes it.
            refreshed_on = datetime.fromtimestamp(self._os_metrics_refreshed_at, tz=timezone.utc).date()
            if time.time() - self._os_metrics_refreshed_at >= 60 or refreshed_on < datetime.now(timezone.utc).date():
                try:
                    self._calculate_os_metrics(wait_for_rebuild=False)
                except Exception as e:
                    log_warning(f"Could not refresh OS metrics before reading them: {str(e)}")

            totals_collection = self._get_collection(
                table_type="os_metrics_totals", create_collection_if_not_found=True
            )
            if totals_collection is None:
                return {}

            sessions_collection = self._get_collection(table_type="sessions")
            today = datetime.now(timezone.utc).date()
            today_start = int(datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
            # A rebuild writes its days oldest first and today last, so a database with sessions and no total
            # row for yesterday, or with sessions today and no total row for today, is still being built
            built_days = {
                document["date"]
                for document in totals_collection.find(
                    {
                        "aggregation_period": "daily",
                        "date": {"$in": [(today - timedelta(days=1)).isoformat(), today.isoformat()]},
                    },
                    {"date": 1},
                )
            }
            if sessions_collection is not None:
                unbuilt_sessions_filter: Optional[Dict[str, Any]] = None
                if (today - timedelta(days=1)).isoformat() not in built_days:
                    unbuilt_sessions_filter = {}
                elif today.isoformat() not in built_days:
                    unbuilt_sessions_filter = {"created_at": {"$gte": today_start}}
                if unbuilt_sessions_filter is not None:
                    if sessions_collection.find_one(unbuilt_sessions_filter, {"session_id": 1}) is not None:
                        # Rows removed while no session or run changed leave the fingerprint as it was
                        self._os_metrics_fingerprint = None
                        return None
            result = totals_collection.find(
                {
                    "aggregation_period": {"$in": ["daily", "monthly"]},
                    "date": {"$gte": starting_date.isoformat(), "$lte": ending_date.isoformat()},
                },
                {"aggregation_period": 1, "date": 1, "version": 1},
            )
            return {f"{document['aggregation_period']} {document['date']}": document["version"] for document in result}

        except Exception as e:
            log_error(f"Error getting OS metrics versions: {str(e)}")
            raise e

    # -- Knowledge methods --

    # Matches rows the user owns plus unowned ones. ``$exists`` covers documents predating the field,
    # which Mongo omits rather than storing as null.
    def _knowledge_user_scope_filter(self, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if user_id is None:
            return None
        return {"$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}]}

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): When set, only deletes rows owned by this user. Unowned rows are shared.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection = self._get_collection(table_type="knowledge")
            if collection is None:
                return

            query: Dict[str, Any] = {"id": id}
            if user_id is not None:
                query["user_id"] = user_id
            collection.delete_one(query)

            log_debug(f"Deleted knowledge content with id '{id}'")

        except Exception as e:
            log_error(f"Error deleting knowledge content: {str(e)}")
            raise e

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): When set, restrict to this user's rows plus unowned ones.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            collection = self._get_collection(table_type="knowledge")
            if collection is None:
                return None

            query: Dict[str, Any] = {"id": id}
            scope = self._knowledge_user_scope_filter(user_id)
            if scope is not None:
                query = {"$and": [query, scope]}
            result = collection.find_one(query)
            if result is None:
                return None

            return KnowledgeRow.model_validate(result)

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
            user_id (Optional[str]): When set, restrict to this user's rows plus unowned ones.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            collection = self._get_collection(table_type="knowledge")
            if collection is None:
                return [], 0

            query: Dict[str, Any] = {}

            # Apply linked_to filter if provided
            if linked_to is not None:
                query["linked_to"] = linked_to

            # Apply owner scoping if provided
            scope = self._knowledge_user_scope_filter(user_id)
            if scope is not None:
                query = {"$and": [query, scope]} if query else scope

            # Get total count
            total_count = collection.count_documents(query)

            # Apply sorting
            sort_criteria = apply_sorting({}, sort_by, sort_order)

            # Apply pagination
            query_args = apply_pagination({}, limit, page)

            cursor = collection.find(query)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            records = list(cursor)
            knowledge_rows = [KnowledgeRow.model_validate(record) for record in records]

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

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            collection = self._get_collection(table_type="knowledge", create_collection_if_not_found=True)
            if collection is None:
                return None

            # A scoped write must not overwrite a doc it does not own
            if knowledge_row.user_id is not None and knowledge_row.id:
                stored = collection.find_one({"id": knowledge_row.id}, {"user_id": 1})
                if stored is not None and stored.get("user_id") != knowledge_row.user_id:
                    raise ValueError(f"Knowledge content {knowledge_row.id} not found")

            update_doc = knowledge_row.model_dump()
            collection.replace_one({"id": knowledge_row.id}, update_doc, upsert=True)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge content: {str(e)}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database."""
        try:
            collection = self._get_collection(table_type="evals", create_collection_if_not_found=True)
            if collection is None:
                return None

            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            collection.insert_one(eval_dict)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            raise e

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the database."""
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return

            result = collection.delete_one({"run_id": eval_run_id})

            if result.deleted_count == 0:
                log_debug(f"No eval run found with ID: {eval_run_id}")
            else:
                log_debug(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {str(e)}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple eval runs from the database."""
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return

            query: Dict[str, Any] = {"run_id": {"$in": eval_run_ids}}
            if user_id is not None:
                query["user_id"] = user_id
            result = collection.delete_many(query)

            if result.deleted_count == 0:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_debug(f"Deleted {result.deleted_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")
            raise e

    def get_eval_run_raw(self, eval_run_id: str) -> Optional[Dict[str, Any]]:
        """Get an eval run from the database as a raw dictionary."""
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return None

            result = collection.find_one({"run_id": eval_run_id})
            return result

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {str(e)}")
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
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return None

            query: Dict[str, Any] = {"run_id": eval_run_id}
            if user_id is not None:
                query["user_id"] = user_id
            eval_run_raw = collection.find_one(query)

            if not eval_run_raw:
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
            create_table_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of eval run dictionaries and the total count

        Raises:
            Exception: If there is an error getting the eval runs.
        """
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return [] if deserialize else ([], 0)

            query: Dict[str, Any] = {}
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if workflow_id is not None:
                query["workflow_id"] = workflow_id
            if model_id is not None:
                query["model_id"] = model_id
            if user_id is not None:
                query["user_id"] = user_id
            if eval_type is not None and len(eval_type) > 0:
                query["eval_type"] = {"$in": eval_type}
            if filter_type is not None:
                if filter_type == EvalFilterType.AGENT:
                    query["agent_id"] = {"$ne": None}
                elif filter_type == EvalFilterType.TEAM:
                    query["team_id"] = {"$ne": None}
                elif filter_type == EvalFilterType.WORKFLOW:
                    query["workflow_id"] = {"$ne": None}

            # Get total count
            total_count = collection.count_documents(query)

            # Apply default sorting by created_at desc if no sort parameters provided
            if sort_by is None:
                sort_criteria = [("created_at", -1)]
            else:
                sort_criteria = apply_sorting({}, sort_by, sort_order)

            # Apply pagination
            query_args = apply_pagination({}, limit, page)

            cursor = collection.find(query)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            records = list(cursor)
            if not records:
                return [] if deserialize else ([], 0)

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
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return None

            query: Dict[str, Any] = {"run_id": eval_run_id}
            if user_id is not None:
                query["user_id"] = user_id
            result = collection.find_one_and_update(
                query,
                {"$set": {"name": name, "updated_at": int(time.time())}},
                return_document=ReturnDocument.AFTER,
            )

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
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return

            collection.update_one({"run_id": eval_run_id}, {"$set": {"user_id": user_id}})

        except Exception as e:
            log_error(f"Error setting owner on eval run {eval_run_id}: {str(e)}")
            raise e

    def migrate_table_from_v1_to_v2(self, v1_db_schema: str, v1_table_name: str, v1_table_type: str):
        """Migrate all content in the given collection to the right v2 collection"""

        from typing import List, Sequence, Union

        from agno.db.migrations.v1_to_v2 import (
            get_all_table_content,
            parse_agent_sessions,
            parse_memories,
            parse_team_sessions,
            parse_workflow_sessions,
        )

        # Get all content from the old collection
        old_content: list[dict[str, Any]] = get_all_table_content(
            db=self,
            db_schema=v1_db_schema,
            table_name=v1_table_name,
        )
        if not old_content:
            log_info(f"No content to migrate from collection {v1_table_name}")
            return

        # Parse the content into the new format
        memories: List[UserMemory] = []
        sessions: Sequence[Union[AgentSession, TeamSession, WorkflowSession]] = []
        if v1_table_type == "agent_sessions":
            sessions = parse_agent_sessions(old_content)
        elif v1_table_type == "team_sessions":
            sessions = parse_team_sessions(old_content)
        elif v1_table_type == "workflow_sessions":
            sessions = parse_workflow_sessions(old_content)
        elif v1_table_type == "memories":
            memories = parse_memories(old_content)
        else:
            raise ValueError(f"Invalid table type: {v1_table_type}")

        # Insert the new content into the new collection
        if v1_table_type == "agent_sessions":
            for session in sessions:
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Agent sessions to collection: {self.session_table_name}")

        elif v1_table_type == "team_sessions":
            for session in sessions:
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Team sessions to collection: {self.session_table_name}")

        elif v1_table_type == "workflow_sessions":
            for session in sessions:
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Workflow sessions to collection: {self.session_table_name}")

        elif v1_table_type == "memories":
            for memory in memories:
                self.upsert_user_memory(memory)
            log_info(f"Migrated {len(memories)} memories to collection: {self.memory_table_name}")

    # --- Traces ---
    def _get_component_level(
        self, workflow_id: Optional[str], team_id: Optional[str], agent_id: Optional[str], name: str
    ) -> int:
        """Get the component level for a trace based on its context.

        Component levels (higher = more important):
            - 3: Workflow root (.run or .arun with workflow_id)
            - 2: Team root (.run or .arun with team_id)
            - 1: Agent root (.run or .arun with agent_id)
            - 0: Child span (not a root)

        Args:
            workflow_id: The workflow ID of the trace.
            team_id: The team ID of the trace.
            agent_id: The agent ID of the trace.
            name: The name of the trace.

        Returns:
            int: The component level (0-3).
        """
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

    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Uses MongoDB's update_one with upsert=True and aggregation pipeline
        to handle concurrent inserts atomically and avoid race conditions.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            collection = self._get_collection(table_type="traces", create_collection_if_not_found=True)
            if collection is None:
                return

            trace_dict = trace.to_dict()
            trace_dict.pop("total_spans", None)
            trace_dict.pop("error_count", None)

            # Calculate the component level for the new trace
            new_level = self._get_component_level(trace.workflow_id, trace.team_id, trace.agent_id, trace.name)

            # Use MongoDB aggregation pipeline update for atomic upsert
            # This allows conditional logic within a single atomic operation
            pipeline: List[Dict[str, Any]] = [
                {
                    "$set": {
                        # Always update these fields
                        "status": trace.status,
                        "created_at": {"$ifNull": ["$created_at", trace_dict.get("created_at")]},
                        # Use $min for start_time (keep earliest)
                        "start_time": {
                            "$cond": {
                                "if": {"$eq": [{"$type": "$start_time"}, "missing"]},
                                "then": trace_dict.get("start_time"),
                                "else": {"$min": ["$start_time", trace_dict.get("start_time")]},
                            }
                        },
                        # Use $max for end_time (keep latest)
                        "end_time": {
                            "$cond": {
                                "if": {"$eq": [{"$type": "$end_time"}, "missing"]},
                                "then": trace_dict.get("end_time"),
                                "else": {"$max": ["$end_time", trace_dict.get("end_time")]},
                            }
                        },
                        # Preserve existing non-null context values: $ifNull returns
                        # the first non-null arg, so put the existing field first.
                        # Otherwise a later upsert from a child span (e.g. a post-hook
                        # agent's run with a different session_id) would overwrite
                        # the trace's already-correct context.
                        "run_id": {"$ifNull": ["$run_id", trace.run_id]},
                        "session_id": {"$ifNull": ["$session_id", trace.session_id]},
                        "user_id": {"$ifNull": ["$user_id", trace.user_id]},
                        "agent_id": {"$ifNull": ["$agent_id", trace.agent_id]},
                        "team_id": {"$ifNull": ["$team_id", trace.team_id]},
                        "workflow_id": {"$ifNull": ["$workflow_id", trace.workflow_id]},
                    }
                },
                {
                    "$set": {
                        # Calculate duration_ms from the (potentially updated) start_time and end_time
                        # MongoDB stores dates as strings in ISO format, so we need to parse them
                        "duration_ms": {
                            "$cond": {
                                "if": {
                                    "$and": [
                                        {"$ne": [{"$type": "$start_time"}, "missing"]},
                                        {"$ne": [{"$type": "$end_time"}, "missing"]},
                                    ]
                                },
                                "then": {
                                    "$subtract": [
                                        {"$toLong": {"$toDate": "$end_time"}},
                                        {"$toLong": {"$toDate": "$start_time"}},
                                    ]
                                },
                                "else": trace_dict.get("duration_ms", 0),
                            }
                        },
                        # Update name based on component level priority
                        # Only update if new trace is from a higher-level component
                        "name": {
                            "$cond": {
                                "if": {"$eq": [{"$type": "$name"}, "missing"]},
                                "then": trace.name,
                                "else": {
                                    "$cond": {
                                        "if": {
                                            "$gt": [
                                                new_level,
                                                {
                                                    "$switch": {
                                                        "branches": [
                                                            # Check if existing name is a root span
                                                            {
                                                                "case": {
                                                                    "$not": {
                                                                        "$or": [
                                                                            {
                                                                                "$regexMatch": {
                                                                                    "input": {"$ifNull": ["$name", ""]},
                                                                                    "regex": "\\.run",
                                                                                }
                                                                            },
                                                                            {
                                                                                "$regexMatch": {
                                                                                    "input": {"$ifNull": ["$name", ""]},
                                                                                    "regex": "\\.arun",
                                                                                }
                                                                            },
                                                                        ]
                                                                    }
                                                                },
                                                                "then": 0,
                                                            },
                                                            # Workflow root (level 3)
                                                            {
                                                                "case": {"$ne": ["$workflow_id", None]},
                                                                "then": 3,
                                                            },
                                                            # Team root (level 2)
                                                            {
                                                                "case": {"$ne": ["$team_id", None]},
                                                                "then": 2,
                                                            },
                                                            # Agent root (level 1)
                                                            {
                                                                "case": {"$ne": ["$agent_id", None]},
                                                                "then": 1,
                                                            },
                                                        ],
                                                        "default": 0,
                                                    }
                                                },
                                            ]
                                        },
                                        "then": trace.name,
                                        "else": "$name",
                                    }
                                },
                            }
                        },
                    }
                },
            ]

            # Perform atomic upsert using aggregation pipeline
            collection.update_one(
                {"trace_id": trace.trace_id},
                pipeline,
                upsert=True,
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

            collection = self._get_collection(table_type="traces")
            if collection is None:
                return None

            # Get spans collection for aggregation
            spans_collection = self._get_collection(table_type="spans")

            query: Dict[str, Any] = {}
            if trace_id:
                query["trace_id"] = trace_id
            elif run_id:
                query["run_id"] = run_id
            else:
                log_debug("get_trace called without any filter parameters")
                return None

            # Find trace with sorting by most recent
            result = collection.find_one(query, sort=[("start_time", -1)])

            if result:
                # Calculate total_spans and error_count from spans collection
                total_spans = 0
                error_count = 0
                if spans_collection is not None:
                    total_spans = spans_collection.count_documents({"trace_id": result["trace_id"]})
                    error_count = spans_collection.count_documents(
                        {"trace_id": result["trace_id"], "status_code": "ERROR"}
                    )

                result["total_spans"] = total_spans
                result["error_count"] = error_count
                # Remove MongoDB's _id field
                result.pop("_id", None)
                return TraceSchema.from_dict(result)
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
        """Get traces matching the provided filters with pagination.

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

            collection = self._get_collection(table_type="traces")
            if collection is None:
                log_debug("Traces collection not found")
                return [], 0

            # Get spans collection for aggregation
            spans_collection = self._get_collection(table_type="spans")

            # Build query
            query: Dict[str, Any] = {}
            if run_id:
                query["run_id"] = run_id
            if session_id:
                query["session_id"] = session_id
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id:
                query["agent_id"] = agent_id
            if team_id:
                query["team_id"] = team_id
            if workflow_id:
                query["workflow_id"] = workflow_id
            if status:
                query["status"] = status
            if start_time:
                query["start_time"] = {"$gte": start_time.isoformat()}
            if end_time:
                if "end_time" in query:
                    query["end_time"]["$lte"] = end_time.isoformat()
                else:
                    query["end_time"] = {"$lte": end_time.isoformat()}

            # Get total count
            total_count = collection.count_documents(query)

            # Apply pagination
            skip = ((page or 1) - 1) * (limit or 20)
            cursor = collection.find(query).sort("start_time", -1).skip(skip).limit(limit or 20)

            results = list(cursor)

            traces = []
            for row in results:
                # Calculate total_spans and error_count from spans collection
                total_spans = 0
                error_count = 0
                if spans_collection is not None:
                    total_spans = spans_collection.count_documents({"trace_id": row["trace_id"]})
                    error_count = spans_collection.count_documents(
                        {"trace_id": row["trace_id"], "status_code": "ERROR"}
                    )

                row["total_spans"] = total_spans
                row["error_count"] = error_count
                # Remove MongoDB's _id field
                row.pop("_id", None)
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
                workflow_id, first_trace_at, last_trace_at.
        """
        if group_by != "session":
            raise NotImplementedError(
                f"get_trace_stats with group_by={group_by!r} is not supported by {self.__class__.__name__}. "
                "Only the default 'session' grouping is available."
            )
        try:
            collection = self._get_collection(table_type="traces")
            if collection is None:
                log_debug("Traces collection not found")
                return [], 0

            # Build match stage
            match_stage: Dict[str, Any] = {"session_id": {"$ne": None}}
            if user_id is not None:
                match_stage["user_id"] = user_id
            if agent_id:
                match_stage["agent_id"] = agent_id
            if team_id:
                match_stage["team_id"] = team_id
            if workflow_id:
                match_stage["workflow_id"] = workflow_id
            if start_time:
                match_stage["created_at"] = {"$gte": start_time.isoformat()}
            if end_time:
                if "created_at" in match_stage:
                    match_stage["created_at"]["$lte"] = end_time.isoformat()
                else:
                    match_stage["created_at"] = {"$lte": end_time.isoformat()}

            # Build aggregation pipeline
            pipeline: List[Dict[str, Any]] = [
                {"$match": match_stage},
                {
                    "$group": {
                        "_id": "$session_id",
                        "user_id": {"$first": "$user_id"},
                        "agent_id": {"$first": "$agent_id"},
                        "team_id": {"$first": "$team_id"},
                        "workflow_id": {"$first": "$workflow_id"},
                        "total_traces": {"$sum": 1},
                        "first_trace_at": {"$min": "$created_at"},
                        "last_trace_at": {"$max": "$created_at"},
                    }
                },
                {"$sort": {"last_trace_at": -1}},
            ]

            # Get total count
            count_pipeline = pipeline + [{"$count": "total"}]
            count_result = list(collection.aggregate(count_pipeline))
            total_count = count_result[0]["total"] if count_result else 0

            # Apply pagination
            skip = ((page or 1) - 1) * (limit or 20)
            pipeline.append({"$skip": skip})
            pipeline.append({"$limit": limit or 20})

            results = list(collection.aggregate(pipeline))

            # Convert to list of dicts with datetime objects
            stats_list = []
            for row in results:
                # Convert ISO strings to datetime objects
                first_trace_at_str = row["first_trace_at"]
                last_trace_at_str = row["last_trace_at"]

                # Parse ISO format strings to datetime objects
                first_trace_at = datetime.fromisoformat(first_trace_at_str.replace("Z", "+00:00"))
                last_trace_at = datetime.fromisoformat(last_trace_at_str.replace("Z", "+00:00"))

                stats_list.append(
                    {
                        "session_id": row["_id"],
                        "user_id": row["user_id"],
                        "agent_id": row["agent_id"],
                        "team_id": row["team_id"],
                        "workflow_id": row["workflow_id"],
                        "total_traces": row["total_traces"],
                        "first_trace_at": first_trace_at,
                        "last_trace_at": last_trace_at,
                    }
                )

            return stats_list, total_count

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
            collection = self._get_collection(table_type="spans", create_collection_if_not_found=True)
            if collection is None:
                return

            collection.insert_one(span.to_dict())

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
            collection = self._get_collection(table_type="spans", create_collection_if_not_found=True)
            if collection is None:
                return

            span_dicts = [span.to_dict() for span in spans]
            collection.insert_many(span_dicts)

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

            collection = self._get_collection(table_type="spans")
            if collection is None:
                return None

            result = collection.find_one({"span_id": span_id})
            if result:
                # Remove MongoDB's _id field
                result.pop("_id", None)
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

            collection = self._get_collection(table_type="spans")
            if collection is None:
                return []

            # Build query
            query: Dict[str, Any] = {}
            if trace_id:
                query["trace_id"] = trace_id
            if parent_span_id:
                query["parent_span_id"] = parent_span_id

            cursor = collection.find(query).limit(limit or 1000)
            results = list(cursor)

            spans = []
            for row in results:
                # Remove MongoDB's _id field
                row.pop("_id", None)
                spans.append(SpanSchema.from_dict(row))

            return spans

        except Exception as e:
            log_error(f"Error getting spans: {str(e)}")
            return []

    # -- Scheduler methods --
    # ``claim_due_schedule`` / ``release_schedule`` stay unscoped so the poller can fire every user's schedules.
    def get_schedule(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            collection = self._get_collection(table_type="schedules")
            if collection is None:
                return None

            query: Dict[str, Any] = {"id": schedule_id}
            if user_id is not None:
                query["user_id"] = user_id
            result = collection.find_one(query)
            if result is None:
                return None

            result.pop("_id", None)
            return result
        except Exception as e:
            log_debug(f"Error getting schedule: {e}")
            return None

    def get_schedule_by_name(self, name: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            collection = self._get_collection(table_type="schedules")
            if collection is None:
                return None

            # Names are unique per owner: ``None`` addresses the unowned bucket
            # ({"user_id": None} matches null and missing), never another owner's schedule.
            query: Dict[str, Any] = {"name": name, "user_id": user_id}
            result = collection.find_one(query)
            if result is None:
                return None

            result.pop("_id", None)
            return result
        except Exception as e:
            log_debug(f"Error getting schedule by name: {e}")
            return None

    def get_schedules(
        self,
        enabled: Optional[bool] = None,
        limit: int = 100,
        page: int = 1,
        user_id: Optional[str] = None,
        raise_on_error: bool = False,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            collection = self._get_collection(table_type="schedules")
            if collection is None:
                if raise_on_error:
                    raise RuntimeError("schedules table unavailable (database error or table never created)")
                return [], 0

            query: Dict[str, Any] = {}
            if enabled is not None:
                query["enabled"] = enabled
            if user_id is not None:
                query["user_id"] = user_id

            total_count = collection.count_documents(query)

            offset = (page - 1) * limit
            # id is a unique tiebreaker so skip/limit pages do not overlap or skip
            # rows when many schedules share a created_at second.
            cursor = collection.find(query).sort([("created_at", -1), ("id", -1)]).skip(offset).limit(limit)
            schedules = list(cursor)
            for schedule in schedules:
                schedule.pop("_id", None)
            return schedules, total_count
        except Exception as e:
            log_debug(f"Error listing schedules: {e}")
            if raise_on_error:
                raise
            return [], 0

    def create_schedule(self, schedule_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            collection = self._get_collection(table_type="schedules", create_collection_if_not_found=True)
            if collection is None:
                raise RuntimeError("Failed to get or create schedules collection")

            collection.insert_one(schedule_data)
            schedule_data.pop("_id", None)
            return schedule_data
        except Exception as e:
            log_error(f"Error creating schedule: {e}")
            raise e

    def update_schedule(
        self, schedule_id: str, user_id: Optional[str] = None, *, preserve_updated_at: bool = False, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        from agno.db.schemas.scheduler import validate_schedule_update

        validate_schedule_update(kwargs)
        if kwargs.get("enabled") is True:
            # A system-set disabled_reason describes why the row was off;
            # turning it on retires the explanation.
            kwargs.setdefault("disabled_reason", None)
        try:
            collection = self._get_collection(table_type="schedules")
            if collection is None:
                return None

            if not preserve_updated_at:
                kwargs["updated_at"] = int(time.time())
            query: Dict[str, Any] = {"id": schedule_id}
            if user_id is not None:
                query["user_id"] = user_id
            result = collection.update_one(query, {"$set": kwargs})
            if result.matched_count == 0:
                return None
            return self.get_schedule(schedule_id, user_id=user_id)
        except Exception as e:
            # Let a unique-violation (rename onto a name taken in the same owner bucket)
            # propagate so the router maps it to 409
            from agno.db.utils import is_unique_violation

            if is_unique_violation(e):
                raise
            log_debug(f"Error updating schedule: {e}")
            return None

    def delete_schedule(self, schedule_id: str, user_id: Optional[str] = None) -> bool:
        try:
            schedules_collection = self._get_collection(table_type="schedules")
            if schedules_collection is None:
                return False

            runs_collection = self._get_collection(table_type="schedule_runs")
            if runs_collection is not None:
                # Mirror the owner guard on the cascade so a shared schedule_id can't drop another user's runs
                runs_query: Dict[str, Any] = {"schedule_id": schedule_id}
                if user_id is not None:
                    runs_query["user_id"] = user_id
                runs_collection.delete_many(runs_query)

            delete_query: Dict[str, Any] = {"id": schedule_id}
            if user_id is not None:
                delete_query["user_id"] = user_id
            result = schedules_collection.delete_one(delete_query)
            return result.deleted_count > 0
        except Exception as e:
            log_debug(f"Error deleting schedule: {e}")
            return False

    def disable_schedules_for_target(
        self,
        target_type: str,
        target_id: str,
        reason: Optional[str] = None,
    ) -> int:
        """Disable every enabled schedule aimed at one component; returns the count.

        Same contract as the SQL adapters: matches provenance-tagged rows
        (target_type/target_id) AND generic rows whose endpoint is that
        component's run endpoint, across owners, recording the system reason in
        disabled_reason.
        """
        from agno.db.schemas.scheduler import build_run_endpoint

        try:
            collection = self._get_collection(table_type="schedules")
            if collection is None:
                return 0
            endpoint = build_run_endpoint(target_type, target_id)
            # RUN_ENDPOINT_RE accepts an optional trailing slash, so a stored
            # "/agents/x/runs/" is a valid run endpoint that plain equality would
            # miss - matching both spellings keeps the cascade from leaking rows.
            result = collection.update_many(
                {
                    "enabled": True,
                    "$or": [
                        {"target_type": target_type, "target_id": target_id},
                        {"endpoint": {"$in": [endpoint, endpoint + "/"]}},
                    ],
                },
                [
                    {
                        "$set": {
                            "enabled": False,
                            "disabled_reason": {"$literal": reason},
                            # An archive cascade is not a user edit, so a Company routine keeps its last-edit time.
                            "updated_at": {
                                "$cond": [{"$eq": ["$managed_by", "company"]}, "$updated_at", int(time.time())]
                            },
                        }
                    }
                ],
            )
            return int(result.modified_count or 0)
        except Exception as e:
            log_error(f"Error disabling schedules for target: {e}")
            raise

    def stamp_schedule_provenance(self, schedule_id: str, **provenance: Any) -> bool:
        """Write provenance columns the generic update_schedule refuses.

        The trusted path for control planes: managed_by, target_type,
        target_id, created_by_*/updated_by_*. Never touches ownership or the
        mutable surface.
        """
        allowed = {
            "managed_by",
            "target_type",
            "target_id",
            "created_by_run_id",
            "created_by_session_id",
            "updated_by_run_id",
            "updated_by_session_id",
        }
        rejected = sorted(set(provenance) - allowed)
        if rejected:
            raise ValueError(f"stamp_schedule_provenance cannot write {rejected}")
        try:
            collection = self._get_collection(table_type="schedules")
            if collection is None:
                return False
            result = collection.update_one(
                {"id": schedule_id},
                {"$set": {"updated_at": int(time.time()), **provenance}},
            )
            return result.matched_count > 0
        except Exception as e:
            log_error(f"Error stamping schedule provenance: {e}")
            raise

    def claim_due_schedule(self, worker_id: str, lock_grace_seconds: int = 300) -> Optional[Dict[str, Any]]:
        try:
            collection = self._get_collection(table_type="schedules")
            if collection is None:
                return None

            now = int(time.time())
            stale_lock_threshold = now - lock_grace_seconds

            result = collection.find_one_and_update(
                {
                    "enabled": True,
                    "next_run_at": {"$lte": now},
                    "$or": [
                        {"locked_by": None},
                        {"locked_at": {"$lte": stale_lock_threshold}},
                    ],
                },
                {"$set": {"locked_by": worker_id, "locked_at": now}},
                sort=[("next_run_at", 1)],
                return_document=ReturnDocument.AFTER,
            )
            if result is None:
                return None

            result.pop("_id", None)
            return result
        except Exception as e:
            log_debug(f"Error claiming schedule: {e}")
            return None

    def release_schedule(
        self,
        schedule_id: str,
        next_run_at: Optional[int] = None,
        *,
        worker_id: Optional[str] = None,
        locked_at: Optional[int] = None,
        preserve_updated_at: bool = False,
    ) -> bool:
        try:
            collection = self._get_collection(table_type="schedules")
            if collection is None:
                return False

            updates: Dict[str, Any] = {"locked_by": None, "locked_at": None}
            if not preserve_updated_at:
                updates["updated_at"] = int(time.time())
            updates["next_run_at"] = {
                "$cond": [
                    {"$eq": ["$cron_expr", ""]},
                    None,
                    next_run_at if next_run_at is not None else "$next_run_at",
                ]
            }

            query: Dict[str, Any] = {"id": schedule_id}
            if worker_id is not None:
                query["locked_by"] = worker_id
            if locked_at is not None:
                query["locked_at"] = locked_at
            result = collection.update_one(query, [{"$set": updates}])
            return result.matched_count > 0
        except Exception as e:
            log_debug(f"Error releasing schedule: {e}")
            return False

    def delete_schedule_runs(self, schedule_id: str, *, before: int) -> int:
        """Expire only completed history for the selected schedule."""
        collection = self._get_collection(table_type="schedule_runs")
        if collection is None:
            return 0
        result = collection.delete_many({"schedule_id": schedule_id, "completed_at": {"$lt": before, "$ne": None}})
        return result.deleted_count

    def create_schedule_run(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            collection = self._get_collection(table_type="schedule_runs", create_collection_if_not_found=True)
            if collection is None:
                raise RuntimeError("Failed to get or create schedule runs collection")

            collection.insert_one(run_data)
            run_data.pop("_id", None)
            return run_data
        except Exception as e:
            log_error(f"Error creating schedule run: {e}")
            raise e

    def update_schedule_run(self, schedule_run_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        try:
            collection = self._get_collection(table_type="schedule_runs")
            if collection is None:
                return None

            result = collection.update_one({"id": schedule_run_id}, {"$set": kwargs})
            if result.matched_count == 0:
                return None
            return self.get_schedule_run(schedule_run_id)
        except Exception as e:
            log_debug(f"Error updating schedule run: {e}")
            return None

    def get_schedule_run(self, run_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            collection = self._get_collection(table_type="schedule_runs")
            if collection is None:
                return None
            query: Dict[str, Any] = {"id": run_id}
            if user_id is not None:
                query["user_id"] = user_id
            result = collection.find_one(query)
            if result is None:
                return None

            result.pop("_id", None)
            return result
        except Exception as e:
            log_debug(f"Error getting schedule run: {e}")
            return None

    def get_latest_schedule_runs(self, schedule_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch the latest run for every requested schedule in one aggregation."""
        if not schedule_ids:
            return {}
        collection = self._get_collection(table_type="schedule_runs")
        if collection is None:
            return {}
        pipeline: List[Dict[str, Any]] = [
            {"$match": {"schedule_id": {"$in": schedule_ids}}},
            {"$sort": {"schedule_id": 1, "triggered_at": -1, "created_at": -1, "id": -1}},
            {"$group": {"_id": "$schedule_id", "run": {"$first": "$$ROOT"}}},
        ]
        latest = {}
        for group in collection.aggregate(pipeline):
            run = group["run"]
            run.pop("_id", None)
            latest[group["_id"]] = run
        return latest

    def get_schedule_runs(
        self,
        schedule_id: str,
        limit: int = 20,
        page: int = 1,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            collection = self._get_collection(table_type="schedule_runs")
            if collection is None:
                return [], 0

            query: Dict[str, Any] = {"schedule_id": schedule_id}
            if user_id is not None:
                query["user_id"] = user_id
            total_count = collection.count_documents(query)

            offset = (page - 1) * limit
            cursor = collection.find(query).sort([("created_at", -1)]).skip(offset).limit(limit)
            runs = list(cursor)
            for run in runs:
                run.pop("_id", None)
            return runs, total_count
        except Exception as e:
            log_debug(f"Error getting schedule runs: {e}")
            return [], 0

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
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return None

            query: Dict[str, Any] = {"learning_type": learning_type}
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if session_id is not None:
                query["session_id"] = session_id
            if namespace is not None:
                query["namespace"] = namespace
            if entity_id is not None:
                query["entity_id"] = entity_id
            if entity_type is not None:
                query["entity_type"] = entity_type

            result = collection.find_one(query)
            if result is None:
                return None
            result.pop("_id", None)
            return {"content": result.get("content")}

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
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=True)
            if collection is None:
                return

            current_time = int(time.time())
            document = {
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
                "updated_at": current_time,
            }
            collection.update_one(
                {"learning_id": id},
                {"$set": document, "$setOnInsert": {"created_at": current_time}},
                upsert=True,
            )
            log_debug(f"Upserted learning: {id}")

        except Exception as e:
            log_debug(f"Error upserting learning: {e}")

    def delete_learning(self, id: str) -> bool:
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return False
            result = collection.delete_one({"learning_id": id})
            return result.deleted_count > 0
        except Exception as e:
            log_debug(f"Error deleting learning: {e}")
            return False

    def update_learning(self, id: str, content: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> bool:
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return False
            # No upsert: only an existing row is updated, never inserted.
            result = collection.update_one(
                {"learning_id": id},
                {"$set": {"content": content, "metadata": metadata, "updated_at": int(time.time())}},
            )
            return result.matched_count > 0
        except Exception as e:
            log_error(f"Error updating learning: {e}")
            raise e

    def delete_user_learnings(self, user_id: str, learning_type: Optional[str] = None) -> int:
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return 0
            query: Dict[str, Any] = {"user_id": user_id}
            if learning_type is not None:
                query["learning_type"] = learning_type
            result = collection.delete_many(query)
            return int(result.deleted_count or 0)
        except Exception as e:
            log_error(f"Error deleting user learnings: {e}")
            raise e

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
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return []

            query: Dict[str, Any] = {}
            if learning_type is not None:
                query["learning_type"] = learning_type
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if session_id is not None:
                query["session_id"] = session_id
            if namespace is not None:
                query["namespace"] = namespace
            if entity_id is not None:
                query["entity_id"] = entity_id
            if entity_type is not None:
                query["entity_type"] = entity_type

            cursor = collection.find(query)
            if limit is not None:
                cursor = cursor.limit(limit)

            learnings = []
            for row in list(cursor):
                row.pop("_id", None)
                learnings.append(row)
            return learnings

        except Exception as e:
            log_debug(f"Error getting learnings: {e}")
            return []

    def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return None
            result = collection.find_one({"learning_id": id})
            if result is None:
                return None
            result.pop("_id", None)
            return result
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
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return [], 0

            query: Dict[str, Any] = {}
            if learning_type is not None:
                query["learning_type"] = learning_type
            if user_id is not None:
                if include_global:
                    query["$or"] = [{"user_id": user_id}, {"user_id": None}]
                else:
                    query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if session_id is not None:
                query["session_id"] = session_id
            if namespace is not None:
                query["namespace"] = namespace
            if entity_id is not None:
                query["entity_id"] = entity_id
            if entity_type is not None:
                query["entity_type"] = entity_type

            total_count = collection.count_documents(query)

            sort_direction = 1 if sort_order == "asc" else -1
            cursor = (
                collection.find(query)
                .sort(sort_by or "updated_at", sort_direction)
                .skip((page - 1) * limit)
                .limit(limit)
            )

            learnings = []
            for row in list(cursor):
                row.pop("_id", None)
                learnings.append(row)
            return learnings, int(total_count)

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
        try:
            collection = self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return [], 0

            # Exclude ownerless records: both explicit null and a missing user_id field
            # (otherwise they group under _id: null and break LearningUserStats validation).
            match_stage: Dict[str, Any] = {"user_id": {"$ne": None, "$exists": True}}
            if learning_type is not None:
                match_stage["learning_type"] = learning_type
            if user_id is not None:
                match_stage["user_id"] = user_id

            # The grouped user_id is the "_id" field after $group.
            sort_field = (
                "_id"
                if (sort_by or "last_learning_updated_at") == "user_id"
                else (sort_by or "last_learning_updated_at")
            )
            sort_direction = 1 if sort_order == "asc" else -1

            pipeline: List[Dict[str, Any]] = [
                {"$match": match_stage},
                {"$group": {"_id": "$user_id", "last_learning_updated_at": {"$max": "$updated_at"}}},
                {"$sort": {sort_field: sort_direction}},
            ]

            count_result = list(collection.aggregate(pipeline + [{"$count": "total"}]))
            total_count = count_result[0]["total"] if count_result else 0

            if limit is not None:
                if page is not None:
                    pipeline.append({"$skip": (page - 1) * limit})
                pipeline.append({"$limit": limit})

            formatted_results = [
                {"user_id": result["_id"], "last_learning_updated_at": result["last_learning_updated_at"]}
                for result in list(collection.aggregate(pipeline))
            ]
            return formatted_results, int(total_count)

        except Exception as e:
            log_error(f"Error getting learning user stats: {e}")
            raise e
