import time
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple, Union
from uuid import uuid4

from agno.db.base import BaseDb, SessionType
from agno.db.in_memory.utils import (
    apply_sorting,
    calculate_date_metrics,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import (
    OS_METRICS_TOTALS_KEY_COLUMNS,
    add_month_os_metrics,
    build_os_metrics_totals_row,
    bulk_upsert_os_metrics,
    calculate_date_os_metrics,
    calculate_month_os_metrics,
    deserialize_history_run,
    deserialize_session,
    deserialize_sessions,
    drop_legacy_metrics,
    filter_context_runs,
    get_months_to_calculate_os_metrics_for,
    get_os_metrics_records_by_day,
    get_os_metrics_rows_by_key,
    get_run_type,
    merge_os_metrics_totals,
    metrics_starting_date_from_records,
    os_metrics_day_completed,
    os_metrics_full_months,
    os_metrics_month_end,
    os_metrics_nested_run_ids,
    os_metrics_rows_to_write,
    os_metrics_totals_row_to_write,
    os_metrics_versions,
    resolve_os_metrics_fields,
    total_os_metrics_rows,
    upsert_os_metrics_totals_row,
)
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace


class InMemoryDb(BaseDb):
    def __init__(self):
        """Interface for in-memory storage."""
        super().__init__()

        # Initialize in-memory storage. Sessions are keyed by session_id so
        # id lookups (get/upsert/delete) stay O(1) as the store grows.
        self._sessions: Dict[str, Dict[str, Any]] = {}
        # Deserialized history-run objects, session_id -> run_id ->
        # (stored run dict, run object). Rebuilding every historical run from
        # its dict on every read made each turn's cost grow with session
        # length. An entry is valid while the stored dict it was built from is
        # still the one in the session's runs list -- upsert_run replaces the
        # dict on every write, so dict identity is the invalidation token, and
        # holding the dict itself means a recycled id can never alias a new
        # dict. The cached objects are shared by every read and immutable by
        # contract; the stored dicts remain the canonical state.
        self._run_object_cache: Dict[str, Dict[str, Tuple[Dict[str, Any], Any]]] = {}
        self._memories: List[Dict[str, Any]] = []
        self._metrics: List[Dict[str, Any]] = []
        self._os_metrics: List[Dict[str, Any]] = []
        self._os_metrics_totals: List[Dict[str, Any]] = []
        self._eval_runs: List[Dict[str, Any]] = []
        self._knowledge: List[Dict[str, Any]] = []
        self._schema_versions: Dict[str, str] = {}

        # The token of the rebuild holding the OS metrics lock, by table
        self._os_metrics_locks: Dict[str, str] = {}
        # Zero means never refreshed; get_os_metrics uses this to refresh lazily, at most once per minute
        self._os_metrics_refreshed_at: float = 0.0
        # The sessions and runs the last refresh read, so a refresh with nothing new is skipped
        self._os_metrics_fingerprint: Optional[Tuple[Any, ...]] = None

    def table_exists(self, table_name: str) -> bool:
        """In-memory implementation, always returns True."""
        return True

    def get_latest_schema_version(self, table_name: str = "") -> Optional[str]:
        """Get the schema version stamped for the given table.

        Defaults to "2.0.0" when nothing is stamped so the MigrationManager
        runs migrations instead of skipping the table.
        """
        return self._schema_versions.get(table_name, "2.0.0")

    def upsert_schema_version(self, table_name: str = "", version: str = "") -> None:
        """Record the schema version stamp for the given table."""
        self._schema_versions[table_name] = version

    # -- Session methods --
    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session from in-memory storage.

        Args:
            session_id (str): The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            bool: True if the session was deleted, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            session = self._sessions.get(session_id)
            if session is not None and (user_id is None or session.get("user_id") == user_id):
                del self._sessions[session_id]
                self._run_object_cache.pop(session_id, None)
                log_debug(f"Successfully deleted session with session_id: {session_id}")
                return True
            else:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False

        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from in-memory storage.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            for session_id in session_ids:
                session = self._sessions.get(session_id)
                if session is not None and (user_id is None or session.get("user_id") == user_id):
                    del self._sessions[session_id]
                    self._run_object_cache.pop(session_id, None)
            log_debug(f"Successfully deleted sessions with ids: {session_ids}")

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
    ) -> Optional[Union[AgentSession, TeamSession, WorkflowSession, Dict[str, Any]]]:
        """Read a session from in-memory storage.

        Args:
            session_id (str): The ID of the session to read.
            session_type (Optional[SessionType]): The type of the session to read.
            user_id (Optional[str]): The ID of the user to read the session for.
            deserialize (Optional[bool]): Whether to deserialize the session.

        Returns:
            Union[Session, Dict[str, Any], None]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs while reading the session.
        """
        try:
            session_data = self._sessions.get(session_id)
            if session_data is None:
                return None
            if user_id is not None and session_data.get("user_id") != user_id:
                return None

            if runs_limit is not None:
                # No query engine to push "last N" down: filter+slice in memory to
                # match the SQL fast path (drop member/skip-status runs, then last N).
                # Slice BEFORE copying so a bounded read copies only the window,
                # not the whole history; the filter only reads the stored dicts.
                runs_window = filter_context_runs(session_data.get("runs") or [])[-runs_limit:]
                session_data_copy = deepcopy({**session_data, "runs": runs_window})
            else:
                if (
                    deserialize
                    and session_data.get("session_type") == SessionType.AGENT.value
                    and (session_type is None or session_type == SessionType.AGENT)
                ):
                    session_obj = self._agent_session_with_cached_runs(session_id, session_data)
                    if session_obj is not None:
                        return session_obj
                session_data_copy = deepcopy(session_data)

            if not deserialize:
                return session_data_copy

            return deserialize_session(session_type, session_data_copy)

        except Exception as e:
            import traceback

            traceback.print_exc()
            log_error(f"Exception reading session: {str(e)}")
            raise e

    def _agent_session_with_cached_runs(self, session_id: str, session_data: Dict[str, Any]) -> Optional[AgentSession]:
        """An AgentSession whose history runs come from the run-object cache.

        The session row is deep-copied and rebuilt fresh per read, so row
        state (session_data, metadata, summary) stays isolated exactly as
        before. History run objects are built once per stored run dict and
        SHARED by every read of the session; see the cache comment in
        __init__ for the invalidation and immutability contract.
        """
        row_copy = deepcopy({**session_data, "runs": None})
        session = AgentSession.from_dict(row_copy)
        if session is None:
            return None

        # Build a fresh entry map and swap it in with one assignment: the map
        # a previous read published is only ever read here, never written, so
        # concurrent readers cannot trip over each other's inserts or sweeps,
        # and entries for deleted runs simply fall out of the new map.
        cache = self._run_object_cache.get(session_id) or {}
        fresh_cache: Dict[str, Tuple[Dict[str, Any], Any]] = {}
        runs: List[Any] = []
        for run_dict in session_data.get("runs") or []:
            if not isinstance(run_dict, dict):
                continue
            run_id = run_dict.get("run_id")
            entry = cache.get(run_id) if run_id is not None else None
            if entry is None or entry[0] is not run_dict:
                # from_dict pops keys from its input, so it gets its own copy;
                # the object then shares nothing with the stored dict.
                entry = (run_dict, deserialize_history_run(deepcopy(run_dict)))
            if run_id is not None:
                fresh_cache[run_id] = entry
            if entry[1] is not None:
                runs.append(entry[1])
        self._run_object_cache[session_id] = fresh_cache

        session.runs = runs
        return session

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
        """Get all sessions from in-memory storage with filtering and pagination.

        Args:
            session_type (SessionType): The type of the sessions to read.
            user_id (Optional[str]): The ID of the user to read the sessions for.
            component_id (Optional[str]): The ID of the component to read the sessions for.
            session_name (Optional[str]): The name of the session to read.
            start_timestamp (Optional[int]): The start timestamp of the sessions to read.
            end_timestamp (Optional[int]): The end timestamp of the sessions to read.
            limit (Optional[int]): The limit of the sessions to read.
            page (Optional[int]): The page of the sessions to read.
            sort_by (Optional[str]): The field to sort the sessions by.
            sort_order (Optional[str]): The order to sort the sessions by.
            deserialize (Optional[bool]): Whether to deserialize the sessions.

        Returns:
            Union[List[AgentSession], List[TeamSession], List[WorkflowSession], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of sessions
                - When deserialize=False: Tuple with list of sessions and total count

        Raises:
            Exception: If an error occurs while reading the sessions.
        """
        try:
            # Apply filters
            filtered_sessions = []
            for session_data in self._sessions.values():
                if user_id is not None and session_data.get("user_id") != user_id:
                    continue
                if component_id is not None:
                    if session_type == SessionType.AGENT and session_data.get("agent_id") != component_id:
                        continue
                    elif session_type == SessionType.TEAM and session_data.get("team_id") != component_id:
                        continue
                    elif session_type == SessionType.WORKFLOW and session_data.get("workflow_id") != component_id:
                        continue
                    elif session_type is None:
                        if (
                            session_data.get("agent_id") != component_id
                            and session_data.get("team_id") != component_id
                            and session_data.get("workflow_id") != component_id
                        ):
                            continue
                if start_timestamp is not None and (session_data.get("created_at") or 0) < start_timestamp:
                    continue
                if end_timestamp is not None and (session_data.get("created_at") or 0) > end_timestamp:
                    continue
                if session_name is not None:
                    stored_name = (session_data.get("session_data") or {}).get("session_name", "")
                    if session_name.lower() not in stored_name.lower():
                        continue
                if session_type is not None:
                    session_type_value = session_type.value if isinstance(session_type, SessionType) else session_type
                    if session_data.get("session_type") != session_type_value:
                        continue

                filtered_sessions.append(deepcopy(session_data))

            total_count = len(filtered_sessions)

            # Apply sorting
            filtered_sessions = apply_sorting(filtered_sessions, sort_by, sort_order)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                filtered_sessions = filtered_sessions[start_idx : start_idx + limit]

            if not include_runs:
                # List views don't need run history; leave it unattached (deepcopy above,
                # so the stored session keeps its runs).
                for s in filtered_sessions:
                    s["runs"] = None

            if not deserialize:
                return filtered_sessions, total_count

            return deserialize_sessions(session_type, filtered_sessions)

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
        try:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session_type is not None and session.get("session_type") != session_type.value:
                return None
            if user_id is not None and session.get("user_id") != user_id:
                return None

            # Update session name in session_data
            if "session_data" not in session or session["session_data"] is None:
                session["session_data"] = {}
            session["session_data"]["session_name"] = session_name

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

            session_copy = deepcopy(session)
            if not deserialize:
                return session_copy

            return deserialize_session(session_type, session_copy)

        except Exception as e:
            log_error(f"Exception renaming session: {str(e)}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        try:
            # Serialize without runs: the runs list on the stored row is
            # maintained incrementally by upsert_run, and re-serializing every
            # run here would make each save cost grow with session length
            # (the SQL adapters already serialize with include_runs=False).
            session_dict = session.to_dict(include_runs=False)

            # Add session_type based on session instance type
            if isinstance(session, AgentSession):
                session_dict["session_type"] = SessionType.AGENT.value
            elif isinstance(session, TeamSession):
                session_dict["session_type"] = SessionType.TEAM.value
            elif isinstance(session, WorkflowSession):
                session_dict["session_type"] = SessionType.WORKFLOW.value

            session_id = session_dict["session_id"]
            existing_session = self._sessions.get(session_id)
            if existing_session is not None:
                # Owner guard, mirroring the SQL adapters' ON CONFLICT ... WHERE
                # clause: an owned session is only writable by its owner; an
                # unowned session can be claimed by anyone.
                existing_uid = existing_session.get("user_id")
                if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                    return None
                session_dict["updated_at"] = int(time.time())
                # A session-row update must never drop runs written by
                # upsert_run: carry the stored list forward. The list is
                # already owned by the store, so it needs no copy.
                runs_for_store = existing_session.get("runs")
            else:
                session_dict["created_at"] = session_dict.get("created_at", int(time.time()))
                session_dict["updated_at"] = session_dict.get("created_at")
                # A delete + re-insert under the same id must not serve the
                # deleted session's cached run objects.
                self._run_object_cache.pop(session_id, None)
                # First insert: serialize whatever runs the incoming session
                # carries, once (bulk import and restore callers never call
                # upsert_run). to_dict output is freshly built, so it needs
                # no defensive copy.
                incoming_runs = session.runs
                runs_for_store = (
                    [run.to_dict() if hasattr(run, "to_dict") else deepcopy(run) for run in incoming_runs]
                    if incoming_runs
                    else None
                )

            stored_session = deepcopy(session_dict)
            stored_session["runs"] = runs_for_store
            self._sessions[session_id] = stored_session

            # Match the SQL adapters' return contract (see SqliteDb.upsert_session):
            # a fresh copy of the session row with the caller's own runs attached
            # by reference. The stored history is never copied or rebuilt on the
            # write path -- doing so made every save cost grow with session
            # length -- and the row copy keeps the returned session detached
            # from both the store and the live session's nested dicts.
            session_row = deepcopy(session_dict)
            if not deserialize:
                session_row["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]
                return session_row

            upserted_session = deserialize_session(None, session_row)
            upserted_session.runs = session.runs  # type: ignore[union-attr]
            return upserted_session

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
            log_info(f"In-memory database: processing {len(sessions)} sessions with individual upsert operations")

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

    # -- Run methods --
    #
    # InMemoryDb keeps runs inline on the session dict (v2.x shape) rather than
    # in a separate collection — no I/O benefit to splitting them. The direct-run
    # APIs below walk the session runs list so callers who use them get the
    # same behaviour as adapters that store runs in a dedicated table.

    def _iter_session_runs(self) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Yield (session_dict, run_dict) pairs across all in-memory sessions."""
        pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for session in self._sessions.values():
            for run in session.get("runs") or []:
                if isinstance(run, dict):
                    pairs.append((session, run))
        return pairs

    def get_run(self, run_id: str, deserialize: Optional[bool] = True) -> Optional[Union[Any, Dict[str, Any]]]:
        """Read a single run from an in-memory session."""
        from agno.db.utils import deserialize_run, get_run_type

        try:
            for session, run in self._iter_session_runs():
                if run.get("run_id") == run_id:
                    run_copy = deepcopy(run)
                    if not deserialize:
                        return run_copy
                    run_type = get_run_type(run_copy)
                    return deserialize_run(run_type, run_copy)
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
        status: Optional[Any] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[Any], Tuple[List[Dict[str, Any]], int]]:
        """Read runs across in-memory sessions with the same filters as SQL adapters."""
        from agno.db.utils import deserialize_run, get_run_type
        from agno.run.base import RunStatus

        try:
            rows: List[Dict[str, Any]] = []
            for session, run in self._iter_session_runs():
                if session_id is not None and session.get("session_id") != session_id:
                    continue
                if user_id is not None and session.get("user_id") != user_id:
                    continue
                if agent_id is not None and run.get("agent_id") != agent_id:
                    continue
                if team_id is not None and run.get("team_id") != team_id:
                    continue
                if workflow_id is not None and run.get("workflow_id") != workflow_id:
                    continue
                if status is not None:
                    expected = status.value if isinstance(status, RunStatus) else status
                    if run.get("status") != expected:
                        continue
                rows.append(deepcopy(run))

            total_count = len(rows)

            if sort_by is not None:
                rows = apply_sorting(rows, sort_by, sort_order)
            else:
                rows.sort(key=lambda r: (r.get("run_index") or 0, r.get("created_at") or 0))

            if limit is not None:
                start_idx = ((page or 1) - 1) * limit if page is not None else 0
                rows = rows[start_idx : start_idx + limit]

            if not deserialize:
                return rows, total_count
            return [deserialize_run(get_run_type(r), r) for r in rows]
        except Exception as e:
            log_error(f"Error reading runs: {str(e)}")
            raise e

    def upsert_run(
        self,
        run: Any,
        session_id: str,
        user_id: Optional[str] = None,
        run_index: Optional[int] = None,
    ) -> None:
        """Upsert a single run into the target session's inline runs list."""
        try:
            # The store keeps its own copy: a dict held by the caller (or the
            # nested structures a live run shares with its to_dict output)
            # must not be able to rewrite stored state in place -- and the
            # run-object cache relies on a stored dict never changing under
            # its identity.
            run_dict = deepcopy(run if isinstance(run, dict) else run.to_dict())
            run_id = run_dict.get("run_id")
            if run_id is None:
                raise ValueError("Run must have a run_id")

            session = self._sessions.get(session_id)
            if session is None:
                log_debug(f"upsert_run: session {session_id} not found; skipping")
                return

            # The stored row holds "runs": None until the first run lands
            runs = session.get("runs") or []
            session["runs"] = runs
            for i, existing in enumerate(runs):
                existing_id = (
                    existing.get("run_id") if isinstance(existing, dict) else getattr(existing, "run_id", None)
                )
                if existing_id == run_id:
                    # Preserve original run_index on update (matches SQL adapters)
                    if isinstance(existing, dict) and "run_index" in existing:
                        run_dict["run_index"] = existing["run_index"]
                    runs[i] = run_dict
                    break
            else:
                if run_index is not None and "run_index" not in run_dict:
                    run_dict["run_index"] = run_index
                runs.append(run_dict)
            session["updated_at"] = int(time.time())
        except Exception as e:
            log_error(f"Error upserting run: {str(e)}")
            raise e

    def delete_run(self, run_id: str) -> bool:
        """Remove a run from its session by run_id."""
        try:
            for session in self._sessions.values():
                runs = session.get("runs") or []
                new_runs = [r for r in runs if not (isinstance(r, dict) and r.get("run_id") == run_id)]
                if len(new_runs) != len(runs):
                    session["runs"] = new_runs
                    session["updated_at"] = int(time.time())
                    return True
            return False
        except Exception as e:
            log_error(f"Error deleting run {run_id}: {str(e)}")
            raise e

    def delete_runs(self, run_ids: List[str]) -> None:
        """Remove multiple runs by run_id across all sessions."""
        if not run_ids:
            return
        wanted = set(run_ids)
        try:
            for session in self._sessions.values():
                runs = session.get("runs") or []
                new_runs = [r for r in runs if not (isinstance(r, dict) and r.get("run_id") in wanted)]
                if len(new_runs) != len(runs):
                    session["runs"] = new_runs
                    session["updated_at"] = int(time.time())
        except Exception as e:
            log_error(f"Error deleting runs: {str(e)}")
            raise e

    # -- Memory methods --
    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from in-memory storage.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user. If provided, verifies the memory belongs to this user before deletion.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            original_count = len(self._memories)

            # If user_id is provided, verify ownership before deleting
            if user_id is not None:
                self._memories = [
                    m for m in self._memories if not (m.get("memory_id") == memory_id and m.get("user_id") == user_id)
                ]
            else:
                self._memories = [m for m in self._memories if m.get("memory_id") != memory_id]

            if len(self._memories) < original_count:
                log_debug(f"Successfully deleted user memory id: {memory_id}")
            else:
                log_debug(f"No memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting memory: {str(e)}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple user memories from in-memory storage.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user. If provided, only deletes memories belonging to this user.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            # If user_id is provided, verify ownership before deleting
            if user_id is not None:
                self._memories = [
                    m for m in self._memories if not (m.get("memory_id") in memory_ids and m.get("user_id") == user_id)
                ]
            else:
                self._memories = [m for m in self._memories if m.get("memory_id") not in memory_ids]
            log_debug(f"Successfully deleted {len(memory_ids)} user memories")

        except Exception as e:
            log_error(f"Error deleting memories: {str(e)}")
            raise e

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from in-memory storage.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            List[str]: List of unique topics.

        Raises:
            Exception: If an error occurs while reading topics.
        """
        try:
            topics = set()
            for memory in self._memories:
                if user_id is not None and memory.get("user_id") != user_id:
                    continue
                memory_topics = memory.get("topics", [])
                if isinstance(memory_topics, list):
                    topics.update(memory_topics)
            return list(topics)

        except Exception as e:
            log_error(f"Exception reading from memory storage: {str(e)}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a user memory from in-memory storage.

        Args:
            memory_id (str): The ID of the memory to retrieve.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user. If provided, only returns the memory if it belongs to this user.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]: The memory object or dictionary, or None if not found.

        Raises:
            Exception: If an error occurs while reading the memory.
        """
        try:
            for memory_data in self._memories:
                if memory_data.get("memory_id") == memory_id:
                    # Filter by user_id if provided
                    if user_id is not None and memory_data.get("user_id") != user_id:
                        continue

                    memory_data_copy = deepcopy(memory_data)
                    if not deserialize:
                        return memory_data_copy
                    return UserMemory.from_dict(memory_data_copy)

            return None

        except Exception as e:
            log_error(f"Exception reading from memory storage: {str(e)}")
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
        try:
            # Apply filters
            filtered_memories = []
            for memory_data in self._memories:
                if user_id is not None and memory_data.get("user_id") != user_id:
                    continue
                if agent_id is not None and memory_data.get("agent_id") != agent_id:
                    continue
                if team_id is not None and memory_data.get("team_id") != team_id:
                    continue
                if topics is not None:
                    memory_topics = memory_data.get("topics", [])
                    if not any(topic in memory_topics for topic in topics):
                        continue
                if search_content is not None:
                    memory_content = str(memory_data.get("memory", ""))
                    if search_content.lower() not in memory_content.lower():
                        continue

                filtered_memories.append(deepcopy(memory_data))

            total_count = len(filtered_memories)

            # Apply sorting
            filtered_memories = apply_sorting(filtered_memories, sort_by, sort_order)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                filtered_memories = filtered_memories[start_idx : start_idx + limit]

            if not deserialize:
                return filtered_memories, total_count

            return [UserMemory.from_dict(memory) for memory in filtered_memories]

        except Exception as e:
            log_error(f"Exception reading from memory storage: {str(e)}")
            raise e

    def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None, user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memory statistics.

        Args:
            limit (Optional[int]): Maximum number of stats to return.
            page (Optional[int]): Page number for pagination.
            user_id (Optional[str]): User ID for filtering.

        Returns:
            Tuple[List[Dict[str, Any]], int]: List of user memory statistics and total count.

        Raises:
            Exception: If an error occurs while getting stats.
        """
        try:
            user_stats = {}

            for memory in self._memories:
                memory_user_id = memory.get("user_id")
                # filter by user_id if provided
                if user_id is not None and memory_user_id != user_id:
                    continue
                if memory_user_id:
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
            stats_list.sort(key=lambda x: x["last_memory_updated_at"], reverse=True)

            total_count = len(stats_list)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                stats_list = stats_list[start_idx : start_idx + limit]

            return stats_list, total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {str(e)}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        try:
            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            memory_dict = memory.to_dict() if hasattr(memory, "to_dict") else memory.__dict__
            memory_dict["updated_at"] = int(time.time())

            # `to_dict()` passes nested values (e.g. `topics`) through by reference, so
            # store a detached copy: mutating the caller's `UserMemory` afterwards would
            # otherwise change what this database already holds, including topic listings.
            stored_memory = deepcopy(memory_dict)

            # Find existing memory to update
            memory_updated = False
            for i, existing_memory in enumerate(self._memories):
                if existing_memory.get("memory_id") == memory.memory_id:
                    self._memories[i] = stored_memory
                    memory_updated = True
                    break

            if not memory_updated:
                self._memories.append(stored_memory)

            memory_dict_copy = deepcopy(memory_dict)
            if not deserialize:
                return memory_dict_copy

            return UserMemory.from_dict(memory_dict_copy)

        except Exception as e:
            log_warning(f"Exception upserting user memory: {str(e)}")
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
            log_info(f"In-memory database: processing {len(memories)} memories with individual upsert operations")
            # For in-memory database, individual upserts are actually efficient
            # since we're just manipulating Python lists and dictionaries
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
        """Delete all memories.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            self._memories.clear()

        except Exception as e:
            log_warning(f"Exception deleting all memories: {str(e)}")
            raise e

    # -- Metrics methods --
    def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics."""
        try:
            starting_date = self._get_metrics_calculation_starting_date(self._metrics)
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

            sessions = self._get_all_sessions_for_metrics_calculation(start_timestamp, end_timestamp)
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

                # One metrics record per user_id: upsert each by (user_id, date, aggregation_period)
                for metrics_record in calculate_date_metrics(date_to_process, sessions_for_date):
                    existing_record_idx = None
                    for i, existing_metric in enumerate(self._metrics):
                        if (
                            existing_metric.get("user_id") == metrics_record["user_id"]
                            and existing_metric.get("date") == str(date_to_process)
                            and existing_metric.get("aggregation_period") == "daily"
                        ):
                            existing_record_idx = i
                            break

                    if existing_record_idx is not None:
                        self._metrics[existing_record_idx] = metrics_record
                    else:
                        self._metrics.append(metrics_record)

                    results.append(metrics_record)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_warning(f"Exception refreshing metrics: {str(e)}")
            raise e

    def _get_metrics_calculation_starting_date(self, metrics: List[Dict[str, Any]]) -> Optional[date]:
        """Get the first date for which metrics calculation is needed."""
        resume_date = metrics_starting_date_from_records(metrics)
        if resume_date is not None:
            return resume_date

        # No metrics records. Return the date of the first recorded session.
        if self._sessions:
            # Sort by created_at
            sorted_sessions = sorted(self._sessions.values(), key=lambda x: x.get("created_at", 0))
            first_session_date = sorted_sessions[0]["created_at"]
            return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

        return None

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions for metrics calculation."""
        try:
            filtered_sessions = []
            for session in self._sessions.values():
                created_at = session.get("created_at", 0)
                if start_timestamp is not None and created_at < start_timestamp:
                    continue
                if end_timestamp is not None and created_at >= end_timestamp:
                    continue

                # Only include necessary fields for metrics
                filtered_session = {
                    "user_id": session.get("user_id"),
                    "session_data": deepcopy(session.get("session_data")),
                    "runs": deepcopy(session.get("runs")),
                    "created_at": session.get("created_at"),
                    "session_type": session.get("session_type"),
                }
                filtered_sessions.append(filtered_session)

            return filtered_sessions

        except Exception as e:
            log_error(f"Exception reading sessions for metrics: {str(e)}")
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
            user_id (Optional[str]): The ID of the user. If provided, only returns that user's records.
        """
        try:
            metrics = drop_legacy_metrics(self._metrics) if user_id is None else self._metrics

            filtered_metrics = []
            latest_updated_at = None

            for metric in metrics:
                metric_date = datetime.strptime(metric.get("date", ""), "%Y-%m-%d").date()

                if starting_date and metric_date < starting_date:
                    continue
                if ending_date and metric_date > ending_date:
                    continue
                if user_id is not None and metric.get("user_id") != user_id:
                    continue

                row = deepcopy(metric)
                # Unowned sessions are bucketed under "": surface them as None
                if row.get("user_id") == "":
                    row["user_id"] = None
                filtered_metrics.append(row)

                updated_at = metric.get("updated_at")
                if updated_at and (latest_updated_at is None or updated_at > latest_updated_at):
                    latest_updated_at = updated_at

            return filtered_metrics, latest_updated_at

        except Exception as e:
            log_error(f"Exception getting metrics: {str(e)}")
            raise e

    # -- OS metrics methods --
    def _get_os_metrics_calculation_starting_date(self, totals_rows: List[Dict[str, Any]]) -> Optional[date]:
        """Get the first date for which OS metrics calculation is needed."""
        resume_date = metrics_starting_date_from_records(
            [row for row in totals_rows if row["aggregation_period"] == "daily"]
        )
        if resume_date is not None:
            return resume_date

        # No total rows. Return the date of the first recorded session.
        if self._sessions:
            # Sort by created_at
            sorted_sessions = sorted(list(self._sessions.values()), key=lambda x: x.get("created_at", 0))
            first_session_date = sorted_sessions[0]["created_at"]
            return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

        return None

    def _lock_os_metrics(self, wait_for_rebuild: bool) -> Optional[str]:
        """Take the lock of the OS metrics rebuild, returning its token, or None when skipped while another holds it."""
        token = uuid4().hex
        # setdefault sets the token only while no other rebuild holds the lock, in one step
        while self._os_metrics_locks.setdefault(self.os_metrics_table_name, token) != token:
            if not wait_for_rebuild:
                return None
            time.sleep(0.1)
        return token

    def _unlock_os_metrics(self, token: str) -> None:
        """Release the lock of the OS metrics rebuild taken with the given token."""
        if self._os_metrics_locks.get(self.os_metrics_table_name) == token:
            del self._os_metrics_locks[self.os_metrics_table_name]

    def _get_all_runs_for_os_metrics_calculation(self) -> List[Dict[str, Any]]:
        """Get all runs for OS metrics calculation, in the shape of a runs table row."""
        runs = []
        # A copy of the sessions, as another thread may add one while they are read
        for session in list(self._sessions.values()):
            for run in session.get("runs") or []:
                if not isinstance(run, dict):
                    continue
                runs.append(
                    {
                        "run_id": run.get("run_id"),
                        "run_type": get_run_type(run),
                        "agent_id": run.get("agent_id"),
                        "team_id": run.get("team_id"),
                        "workflow_id": run.get("workflow_id"),
                        # A run is owned by its own user, as the runs table stores it, else by the user of its session
                        "user_id": run.get("user_id") or session.get("user_id"),
                        "parent_run_id": run.get("parent_run_id"),
                        "status": run.get("status"),
                        "run_data": run,
                        "created_at": run.get("created_at"),
                        # Every write of a run stamps its session, so the run changed when its session did
                        "updated_at": session.get("updated_at"),
                    }
                )
        return runs

    def _calculate_month_os_metrics(
        self,
        rows_by_key: Dict[Tuple[Any, ...], Dict[str, Any]],
        totals_by_key: Dict[Tuple[Any, ...], Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Calculate the month rows of every completed month that has none."""
        results: List[Dict[str, Any]] = []
        total_rows = list(totals_by_key.values())
        day_starts = [row["date"] for row in total_rows if row["aggregation_period"] == "daily"]
        calculated_months = [row["date"] for row in total_rows if row["aggregation_period"] == "monthly"]
        latest_completed = max(
            (row["date"] for row in total_rows if row["aggregation_period"] == "daily" and row["completed"]),
            default=None,
        )
        for month_start in get_months_to_calculate_os_metrics_for(day_starts, calculated_months, latest_completed):
            stored_rows = [
                row
                for row in rows_by_key.values()
                if row["aggregation_period"] == "daily"
                and month_start <= row["date"] <= os_metrics_month_end(month_start)
            ]

            per_owner: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
            add_month_os_metrics(per_owner, stored_rows)

            month_rows = calculate_month_os_metrics(month_start, per_owner)
            bulk_upsert_os_metrics(rows_by_key, month_rows)
            totals_row = build_os_metrics_totals_row(month_rows, "monthly", month_start, completed=True)
            upsert_os_metrics_totals_row(totals_by_key, totals_row)
            results.append(totals_row)

        if results:
            # Written last: a read takes a month from its rows only once the month has a total row
            self._os_metrics = list(rows_by_key.values())
            self._os_metrics_totals = list(totals_by_key.values())

        return results

    def _get_os_metrics_fingerprint(
        self, sessions: List[Dict[str, Any]], runs: List[Dict[str, Any]], dates_to_process: List[date]
    ) -> Optional[Tuple[Any, ...]]:
        """Get the count and update times of the sessions and runs of the given dates. None while one of them was
        updated in the current second, which a second update in that same second would leave unchanged."""
        start_timestamp = int(
            datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
        )
        current_time = int(time.time())
        fingerprint: List[Any] = [dates_to_process[0], dates_to_process[-1]]
        for records in [sessions, runs]:
            updated_ats = [
                record.get("updated_at") or 0
                for record in records
                if (record.get("created_at") or 0) >= start_timestamp
            ]
            if updated_ats and max(updated_ats) >= current_time:
                return None
            fingerprint.extend([len(updated_ats), sum(updated_ats)])
        return tuple(fingerprint)

    def _calculate_os_metrics(
        self, wait_for_rebuild: bool
    ) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
        """Calculate OS metrics for all dates without complete OS metrics."""
        # Stamp first so failed runs are throttled too instead of retried on every read
        self._os_metrics_refreshed_at = time.time()

        starting_date = self._get_os_metrics_calculation_starting_date(self._os_metrics_totals)

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

        start_timestamp = int(
            datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
        )
        end_timestamp = int(
            datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        sessions = list(self._sessions.values())
        runs = self._get_all_runs_for_os_metrics_calculation()

        # Read before the days, so a session or run written while they are rebuilt moves the next one
        fingerprint = self._get_os_metrics_fingerprint(sessions, runs, dates_to_process)
        if not wait_for_rebuild and fingerprint is not None and fingerprint == self._os_metrics_fingerprint:
            return None

        # One rebuild at a time: a second one waits here, or skips when told not to wait
        lock_token = self._lock_os_metrics(wait_for_rebuild)
        if lock_token is None:
            # Reset the throttle so the next read tries again
            self._os_metrics_refreshed_at = 0.0
            log_info("Another thread is calculating OS metrics. Won't calculate OS metrics.")
            return None

        results = []
        written_totals_rows: List[Dict[str, Any]] = []
        try:
            # Read under the lock, so what a rebuild this one waited for counted and wrote is kept
            sessions = list(self._sessions.values())
            runs = self._get_all_runs_for_os_metrics_calculation()
            rows_by_key = get_os_metrics_rows_by_key(self._os_metrics)
            totals_by_key = get_os_metrics_rows_by_key(self._os_metrics_totals, OS_METRICS_TOTALS_KEY_COLUMNS)
            stored_rows_by_day: Dict[date, List[Dict[str, Any]]] = {}
            for row in rows_by_key.values():
                if row["aggregation_period"] == "daily":
                    stored_rows_by_day.setdefault(row["date"], []).append(row)
            latest_completed = max(
                (
                    row["date"]
                    for row in totals_by_key.values()
                    if row["aggregation_period"] == "daily" and row["completed"]
                ),
                default=None,
            )

            sessions_by_day = get_os_metrics_records_by_day(sessions, start_timestamp, end_timestamp)
            runs_by_day = get_os_metrics_records_by_day(runs, start_timestamp, end_timestamp)
            run_ids = {run["run_id"] for run in runs if run.get("run_id")}
            runs_by_id = {run["run_id"]: run for run in runs if run.get("run_id")}

            rows_changed = False
            try:
                for date_to_process in dates_to_process:
                    # Skip a day a rebuild this one waited for has completed
                    if latest_completed is not None and date_to_process <= latest_completed:
                        continue

                    day_runs = runs_by_day.get(date_to_process, [])
                    # A nested run also stored as a run of its own is counted from that row, whatever day it is on
                    stored_run_ids = os_metrics_nested_run_ids(day_runs) & run_ids

                    # A run started by a run of another day, such as a member run after midnight, names that run's
                    # agent, team or workflow as its parent, read from every run of the rebuild
                    day_run_ids = {run["run_id"] for run in day_runs if run.get("run_id")}
                    parent_runs = [
                        runs_by_id[run_id]
                        for run_id in sorted(
                            {run["parent_run_id"] for run in day_runs if run.get("parent_run_id")} - day_run_ids
                        )
                        if run_id in runs_by_id
                    ]

                    records = calculate_date_os_metrics(
                        date_to_process,
                        sessions_by_day.get(date_to_process, []),
                        day_runs,
                        stored_run_ids,
                        parent_runs,
                    )
                    changed_rows, stale_keys = os_metrics_rows_to_write(
                        records, stored_rows_by_day.get(date_to_process, [])
                    )
                    # Built before the day's rows change, as no transaction undoes a day that fails
                    totals_row = os_metrics_totals_row_to_write(
                        build_os_metrics_totals_row(
                            records, "daily", date_to_process, os_metrics_day_completed(date_to_process)
                        ),
                        totals_by_key.get(("daily", date_to_process)),
                        rows_changed=bool(changed_rows or stale_keys),
                    )
                    for stale_key in stale_keys:
                        rows_by_key.pop(("daily", date_to_process) + stale_key)
                    bulk_upsert_os_metrics(rows_by_key, changed_rows)
                    rows_changed = rows_changed or bool(changed_rows or stale_keys)
                    if totals_row is not None:
                        upsert_os_metrics_totals_row(totals_by_key, totals_row)
                        written_totals_rows.append(totals_row)
                    results.extend(records)
            finally:
                # Written even when a later day fails, as new lists so a read never sees one half written.
                # The total rows go last, so a version never moves without the rows it tells of
                if rows_changed:
                    self._os_metrics = list(rows_by_key.values())
                if written_totals_rows:
                    self._os_metrics_totals = list(totals_by_key.values())

            written_totals_rows.extend(self._calculate_month_os_metrics(rows_by_key, totals_by_key))
        finally:
            self._unlock_os_metrics(lock_token)

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
        """Total the OS metrics of the given date range, every day from one period."""
        # Each list is replaced whole, and the total rows are written after the rows, so the rows read after the
        # total rows hold every month the total rows tell of
        totals_rows = self._os_metrics_totals
        # Every owner is read from the total rows, one owner from that owner's rows
        rows = totals_rows if user_id is None else self._os_metrics

        full_months = os_metrics_full_months(starting_date, ending_date) if use_month_rows else []
        # A month's total row is written after its rows, so a month that has one is read from its rows
        month_starts = [
            row["date"] for row in totals_rows if row["aggregation_period"] == "monthly" and row["date"] in full_months
        ]
        return total_os_metrics_rows(rows, starting_date, ending_date, user_id, fields, month_starts=month_starts)

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
            log_error(f"Exception refreshing OS metrics: {str(e)}")
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
            # A period's total row is written with every write of its rows, so the newest total row is the newest write
            previous_updated_at = max(
                (row["updated_at"] for row in self._os_metrics_totals if row.get("updated_at") is not None),
                default=None,
            )

            calculation = self._calculate_os_metrics(wait_for_rebuild=True)
            written_totals_rows: List[Dict[str, Any]] = []
            if calculation is not None:
                _, written_totals_rows = calculation

            latest_updated_at = max(
                (row["updated_at"] for row in self._os_metrics_totals if row.get("updated_at") is not None),
                default=None,
            )

            return previous_updated_at, latest_updated_at, bool(written_totals_rows)

        except Exception as e:
            log_error(f"Exception refreshing OS metrics: {str(e)}")
            raise e

    def get_os_metrics(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Get the OS metrics totals of each day in the given date range.

        OS metrics are refreshed lazily, at most once per minute, without waiting for a rebuild another thread is
        running. For every owner, each day is read from its total row; for one owner, from its rows.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner.
            fields (Optional[List[str]]): The columns to total. ``None`` totals all.

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
            log_error(f"Exception getting OS metrics: {str(e)}")
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
            fields (Optional[List[str]]): The columns to total. ``None`` totals all.

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
            log_error(f"Exception getting OS metrics totals: {str(e)}")
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

            totals_rows = self._os_metrics_totals

            today = datetime.now(timezone.utc).date()
            today_start = int(datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
            # A rebuild writes its days oldest first and today last, so a database with sessions and no total
            # row for yesterday, or with sessions today and no total row for today, is still being built
            built_days = {
                row["date"]
                for row in totals_rows
                if row["aggregation_period"] == "daily" and row["date"] in [today - timedelta(days=1), today]
            }
            unbuilt_sessions: List[Dict[str, Any]] = []
            if today - timedelta(days=1) not in built_days:
                unbuilt_sessions = list(self._sessions.values())
            elif today not in built_days:
                unbuilt_sessions = [
                    session
                    for session in list(self._sessions.values())
                    if (session.get("created_at") or 0) >= today_start
                ]
            if unbuilt_sessions:
                # Rows removed while no session or run changed leave the fingerprint as it was
                self._os_metrics_fingerprint = None
                return None

            return os_metrics_versions([row for row in totals_rows if starting_date <= row["date"] <= ending_date])

        except Exception as e:
            log_error(f"Exception getting OS metrics versions: {str(e)}")
            raise e

    # -- Knowledge methods --

    @staticmethod
    def _knowledge_item_is_visible(item: Dict[str, Any], user_id: Optional[str]) -> bool:
        if user_id is None:
            return True
        owner = item.get("user_id")
        return owner is None or owner == user_id

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from in-memory storage.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): The ID of the user. If provided, only deletes rows owned by this user.
                Unowned rows are shared content and are never deleted by a scoped call.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            self._knowledge = [
                item
                for item in self._knowledge
                if not (item.get("id") == id and (user_id is None or item.get("user_id") == user_id))
            ]

        except Exception as e:
            log_error(f"Error deleting knowledge content: {str(e)}")
            raise e

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from in-memory storage.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): The ID of the user. If provided, only returns rows owned by this
                user or unowned (shared) rows.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            for item in self._knowledge:
                if item.get("id") == id and self._knowledge_item_is_visible(item, user_id):
                    return KnowledgeRow.model_validate(item)

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
        """Get all knowledge contents from in-memory storage.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).
            user_id (Optional[str]): The ID of the user. If provided, only returns rows owned by this
                user or unowned (shared) rows.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            knowledge_items = [deepcopy(item) for item in self._knowledge]

            # Apply linked_to filter if provided
            if linked_to is not None:
                knowledge_items = [item for item in knowledge_items if item.get("linked_to") == linked_to]

            # Apply user_id filter if provided
            if user_id is not None:
                knowledge_items = [item for item in knowledge_items if self._knowledge_item_is_visible(item, user_id)]

            total_count = len(knowledge_items)

            # Apply sorting
            knowledge_items = apply_sorting(knowledge_items, sort_by, sort_order)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                knowledge_items = knowledge_items[start_idx : start_idx + limit]

            return [KnowledgeRow.model_validate(item) for item in knowledge_items], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {str(e)}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            knowledge_dict = knowledge_row.model_dump()

            # Find existing item to update
            item_updated = False
            for i, existing_item in enumerate(self._knowledge):
                if existing_item.get("id") == knowledge_row.id:
                    # A scoped write must not overwrite an item it does not own
                    if knowledge_row.user_id is not None and existing_item.get("user_id") != knowledge_row.user_id:
                        raise ValueError(f"Knowledge content {knowledge_row.id} not found")
                    self._knowledge[i] = knowledge_dict
                    item_updated = True
                    break

            if not item_updated:
                self._knowledge.append(knowledge_dict)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge row: {str(e)}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord"""
        try:
            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            self._eval_runs.append(eval_dict)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple eval runs from in-memory storage."""
        try:
            original_count = len(self._eval_runs)
            self._eval_runs = [
                run
                for run in self._eval_runs
                if not (run.get("run_id") in eval_run_ids and (user_id is None or run.get("user_id") == user_id))
            ]

            deleted_count = original_count - len(self._eval_runs)
            if deleted_count > 0:
                log_debug(f"Deleted {deleted_count} eval runs")
            else:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")
            raise e

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from in-memory storage."""
        try:
            for run_data in self._eval_runs:
                if run_data.get("run_id") == eval_run_id:
                    if user_id is not None and run_data.get("user_id") != user_id:
                        return None
                    run_data_copy = deepcopy(run_data)
                    if not deserialize:
                        return run_data_copy
                    return EvalRunRecord.model_validate(run_data_copy)

            return None

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
        """Get all eval runs from in-memory storage with filtering and pagination."""
        try:
            # Apply filters
            filtered_runs = []
            for run_data in self._eval_runs:
                if agent_id is not None and run_data.get("agent_id") != agent_id:
                    continue
                if team_id is not None and run_data.get("team_id") != team_id:
                    continue
                if workflow_id is not None and run_data.get("workflow_id") != workflow_id:
                    continue
                if model_id is not None and run_data.get("model_id") != model_id:
                    continue
                if user_id is not None and run_data.get("user_id") != user_id:
                    continue
                if eval_type is not None and len(eval_type) > 0:
                    if run_data.get("eval_type") not in eval_type:
                        continue
                if filter_type is not None:
                    if filter_type == EvalFilterType.AGENT and run_data.get("agent_id") is None:
                        continue
                    elif filter_type == EvalFilterType.TEAM and run_data.get("team_id") is None:
                        continue
                    elif filter_type == EvalFilterType.WORKFLOW and run_data.get("workflow_id") is None:
                        continue

                filtered_runs.append(deepcopy(run_data))

            total_count = len(filtered_runs)

            # Apply sorting (default by created_at desc)
            if sort_by is None:
                filtered_runs.sort(key=lambda x: x.get("created_at", 0), reverse=True)
            else:
                filtered_runs = apply_sorting(filtered_runs, sort_by, sort_order)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                filtered_runs = filtered_runs[start_idx : start_idx + limit]

            if not deserialize:
                return filtered_runs, total_count

            return [EvalRunRecord.model_validate(run) for run in filtered_runs]

        except Exception as e:
            log_error(f"Exception getting eval runs: {str(e)}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Rename an eval run."""
        try:
            for i, run_data in enumerate(self._eval_runs):
                if run_data.get("run_id") == eval_run_id:
                    if user_id is not None and run_data.get("user_id") != user_id:
                        return None
                    run_data["name"] = name
                    run_data["updated_at"] = int(time.time())
                    self._eval_runs[i] = run_data

                    log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

                    run_data_copy = deepcopy(run_data)
                    if not deserialize:
                        return run_data_copy

                    return EvalRunRecord.model_validate(run_data_copy)

            return None

        except Exception as e:
            log_error(f"Error renaming eval run {eval_run_id}: {str(e)}")
            raise e

    def update_eval_run_user_id(self, eval_run_id: str, user_id: str) -> None:
        """Set the owner (user_id) on an existing eval run.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            user_id (str): The owner to set.
        """
        try:
            for run_data in self._eval_runs:
                if run_data.get("run_id") == eval_run_id:
                    run_data["user_id"] = user_id
                    break

        except Exception as e:
            log_error(f"Error setting owner on eval run {eval_run_id}: {str(e)}")
            raise e

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

    # --- Spans ---
    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        raise NotImplementedError

    def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        raise NotImplementedError

    def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError("Learning methods not yet implemented for InMemoryDb")

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
        raise NotImplementedError("Learning methods not yet implemented for InMemoryDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for InMemoryDb")

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
        raise NotImplementedError("Learning methods not yet implemented for InMemoryDb")
