"""Logic shared across different database implementations"""

import json
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from os import getenv
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple, Union
from uuid import UUID

from agno import __version__ as agno_version
from agno.exceptions import MigrationRequiredError, SchemaMismatchError
from agno.metrics import ModelMetrics, RunMetrics, SessionMetrics
from agno.models.message import Message
from agno.run.base import HISTORY_SKIP_STATUSES as _RUN_HISTORY_SKIP_STATUSES
from agno.run.base import RunStatus
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb, SessionType
    from agno.registry.registry import Registry
    from agno.session import Session


# Keys in a serialized db dict that correspond to table-name overrides.
# Matches the parameters BaseDb.__init__ accepts for customizing table names.
DB_TABLE_NAME_KEYS: frozenset = frozenset(
    {
        "session_table",
        "job_table",
        "runs_table",
        "memory_table",
        "metrics_table",
        "component_metrics_table",
        "aggregate_metrics_table",
        "metrics_refreshes_table",
        "eval_table",
        "knowledge_table",
        "traces_table",
        "spans_table",
        "versions_table",
        "components_table",
        "component_configs_table",
        "component_links_table",
        "learnings_table",
        "schedules_table",
        "products_table",
        "sources_table",
        "projects_table",
        "tasks_table",
        "schedule_runs_table",
        "approvals_table",
        "auth_tokens_table",
        "service_accounts_table",
        "mcp_oauth_clients_table",
        "mcp_oauth_codes_table",
        "mcp_oauth_refresh_tokens_table",
        "mcp_oauth_transactions_table",
        "mcp_oauth_keys_table",
    }
)


def is_unique_violation(exc: Exception) -> bool:
    """Whether ``exc`` is a DB unique-constraint / duplicate-key violation.

    Matched by exception TYPE (SQLAlchemy ``IntegrityError`` for pg/sqlite, pymongo
    ``DuplicateKeyError`` for Mongo), never by message text — SQLAlchemy folds bound
    parameters into ``str(exc)``, so a substring check could misfire on caller data.
    Used by ``update_schedule`` to let a rename-onto-taken-name propagate (so the
    router can map it to 409) while all other DB errors keep swallowing to None.
    """
    try:
        from sqlalchemy.exc import IntegrityError

        if isinstance(exc, IntegrityError):
            return True
    except ImportError:
        pass
    try:
        from pymongo.errors import DuplicateKeyError

        if isinstance(exc, DuplicateKeyError):
            return True
    except ImportError:
        pass
    return False


def database_error_message(exc: Exception) -> str:
    """The first line of the database's own message for ``exc``, without the statement and parameters SQLAlchemy
    folds into ``str(exc)``."""
    return str(getattr(exc, "orig", exc)).partition("\n")[0]


def detect_session_type(record: Dict[str, Any]) -> str:
    """Detect session type from a raw session dict, inferring from component IDs if needed.

    Priority: stored session_type > component IDs (agent_id > team_id > workflow_id) > fallback "agent".

    Args:
        record: Raw session dictionary.

    Returns:
        Session type string ("agent", "team", or "workflow").
    """
    st = record.get("session_type")
    if st:
        return st.value if hasattr(st, "value") else st
    if record.get("agent_id"):
        return "agent"
    if record.get("team_id"):
        return "team"
    if record.get("workflow_id"):
        return "workflow"
    return "agent"


def deserialize_history_run(run_dict: Dict[str, Any]) -> Optional[Any]:
    """One stored run dict as a run object, mirroring AgentSession.from_dict's
    per-run dispatch (a dict matching neither shape is skipped there too)."""
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

    if "agent_id" in run_dict:
        return RunOutput.from_dict(run_dict)
    if "team_id" in run_dict:
        return TeamRunOutput.from_dict(run_dict)
    return None


class SessionRunObjectCache:
    """Deserialized history-run objects for one db adapter, keyed per run by
    the raw JSON text of its row.

    Rebuilding every historical run from its row on every read made per-turn
    conversation cost grow with session length. An adapter that can read the
    run column as text builds each run object once and shares it across
    reads: the validity token is (hash, length) of the text, so ANY write to
    the run -- from this process or another one -- changes the text and
    misses the cache. Shared objects are immutable by contract (every library
    path that changes a historical run copies it first) and nothing ever
    serializes them back to the store; the rows stay canonical.

    Sessions are pruned least-recently-read beyond ``max_sessions``, and a
    read replaces the session's entry map wholesale, so deleted runs do not
    linger.

    The token must never be persisted or shared between processes: ``hash`` is
    randomized per process, so the same text yields different tokens in
    different processes (and after a restart). It is only meaningful within the
    lifetime of one adapter instance, which is the only place it is used.
    """

    def __init__(self, max_sessions: int = 64):
        from collections import OrderedDict

        self._per_session: "OrderedDict[str, Dict[str, Tuple[Tuple[int, int], Any]]]" = OrderedDict()
        self._max_sessions = max_sessions

    def runs_from_rows(self, session_id: str, rows: Sequence[Tuple[str, str]]) -> List[Any]:
        """The run objects for ``rows`` of (run_id, raw run_data text), in order."""
        cache = self._per_session.pop(session_id, None) or {}
        fresh: Dict[str, Tuple[Tuple[int, int], Any]] = {}
        objects: List[Any] = []
        for run_id, text in rows:
            token = (hash(text), len(text))
            entry = cache.get(run_id)
            if entry is None or entry[0] != token:
                entry = (token, deserialize_history_run(json.loads(text)))
            fresh[run_id] = entry
            if entry[1] is not None:
                objects.append(entry[1])
        self._per_session[session_id] = fresh
        while len(self._per_session) > self._max_sessions:
            self._per_session.popitem(last=False)
        return objects

    def drop_session(self, session_id: str) -> None:
        self._per_session.pop(session_id, None)


def deserialize_session_by_type(record: Dict[str, Any]) -> "Session":
    """Deserialize a raw session dict into the correct Session subclass based on detected type.

    Args:
        record: Raw session dictionary.

    Returns:
        Session subclass instance (AgentSession, TeamSession, or WorkflowSession).
    """
    from agno.session import AgentSession, TeamSession, WorkflowSession

    st = detect_session_type(record)
    if st == "agent":
        return AgentSession.from_dict(record)  # type: ignore
    elif st == "team":
        return TeamSession.from_dict(record)  # type: ignore
    elif st == "workflow":
        return WorkflowSession.from_dict(record)  # type: ignore
    return AgentSession.from_dict(record)  # type: ignore


def deserialize_session(session_type: Optional["SessionType"], record: Dict[str, Any]) -> "Session":
    """Deserialize a raw session dict into the correct Session subclass.

    Args:
        session_type: The type to deserialize as. If None, auto-detects from the record's component IDs.
        record: Raw session dictionary.

    Returns:
        Session subclass instance (AgentSession, TeamSession, or WorkflowSession).

    Raises:
        ValueError: If session_type is not a valid SessionType.
    """
    from agno.db.base import SessionType
    from agno.session import AgentSession, TeamSession, WorkflowSession

    if session_type is None:
        return deserialize_session_by_type(record)
    if session_type == SessionType.AGENT:
        return AgentSession.from_dict(record)  # type: ignore
    elif session_type == SessionType.TEAM:
        return TeamSession.from_dict(record)  # type: ignore
    elif session_type == SessionType.WORKFLOW:
        return WorkflowSession.from_dict(record)  # type: ignore
    raise ValueError(f"Invalid session type: {session_type}")


def deserialize_sessions(session_type: Optional["SessionType"], records: List[Dict[str, Any]]) -> List["Session"]:
    """Deserialize a list of raw session dicts into the correct Session subclasses.

    Args:
        session_type: The type to deserialize as. If None, auto-detects each record individually.
        records: List of raw session dictionaries.

    Returns:
        List of Session subclass instances.
    """
    return [deserialize_session(session_type, record) for record in records]


def get_run_type(run: Any) -> str:
    """Return the run type ("agent", "team" or "workflow") for the given run object or dict."""
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput
    from agno.run.workflow import WorkflowRunOutput

    if isinstance(run, RunOutput):
        return "agent"
    if isinstance(run, TeamRunOutput):
        return "team"
    if isinstance(run, WorkflowRunOutput):
        return "workflow"
    if isinstance(run, dict):
        # A member run persisted without its id still identifies itself by name.
        if run.get("agent_id") or run.get("agent_name"):
            return "agent"
        if run.get("team_id") or run.get("team_name"):
            return "team"
        return "workflow"
    raise ValueError(f"Cannot determine run type for: {type(run)}")


def deserialize_run(run_type: Optional[str], run_data: Dict[str, Any]) -> Any:
    """Deserialize a run dict into the correct run output class based on its type."""
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput
    from agno.run.workflow import WorkflowRunOutput

    # Some JSON columns (MySQL/SingleStore drivers, SQLite TEXT) hand back the
    # payload as a str rather than a dict; normalize before dispatching.
    if isinstance(run_data, str):
        run_data = json.loads(run_data)

    if run_type is None:
        run_type = get_run_type(run_data)
    if run_type == "agent":
        return RunOutput.from_dict(run_data)
    if run_type == "team":
        return TeamRunOutput.from_dict(run_data)
    if run_type == "workflow":
        return WorkflowRunOutput.from_dict(run_data)
    raise ValueError(f"Invalid run type: {run_type}")


def build_run_rows_for_session(session: "Session") -> List[Dict[str, Any]]:
    """Build runs-table rows for every run in the given session.

    Args:
        session: The session whose runs should be persisted.

    Returns:
        List of row dicts matching the runs table schema (run_data is the raw run dict).
    """
    current_time = int(time.time())
    rows: List[Dict[str, Any]] = []
    for run_index, run in enumerate(session.runs or []):
        run_id = run.get("run_id") if isinstance(run, dict) else getattr(run, "run_id", None)
        if run_id is None:
            continue

        run_data = run if isinstance(run, dict) else run.to_dict()
        rows.append(
            {
                "run_id": run_id,
                "session_id": session.session_id,
                "run_type": get_run_type(run),
                "agent_id": run_data.get("agent_id"),
                "team_id": run_data.get("team_id"),
                "workflow_id": run_data.get("workflow_id"),
                "user_id": session.user_id,
                "parent_run_id": run_data.get("parent_run_id"),
                "status": run_data.get("status"),
                "run_index": run_index,
                "run_data": run_data,
                "created_at": run_data.get("created_at") or current_time,
                "updated_at": current_time,
            }
        )

    return rows


def run_index_lock_name(session_id: str) -> str:
    """Per-session named-lock key serializing run_index backfills on engines
    with connection-scoped user locks (MySQL GET_LOCK). Hashed because MySQL
    caps lock names at 64 characters and session ids are caller-provided."""
    import hashlib

    return "agno_run_index_" + hashlib.md5(session_id.encode()).hexdigest()


def canonical_run_status(value: Any) -> Any:
    """Map a run status of any casing or enum form to the stored convention:
    ``RunStatus.value`` (uppercase, e.g. ``"COMPLETED"``).

    The indexed ``status`` column is filtered case-sensitively (``get_runs``
    compares against ``RunStatus.value``), so a writer that stores
    ``"completed"`` verbatim produces rows invisible to those readers.
    Unknown values pass through unchanged.
    """
    from agno.run.base import RunStatus

    if isinstance(value, RunStatus):
        return value.value
    try:
        return RunStatus(str(value)).value
    except ValueError:
        pass
    try:
        return RunStatus[str(value).lower()].value
    except KeyError:
        return value


def build_single_run_row(
    run: Any,
    session_id: str,
    user_id: Optional[str] = None,
    run_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a single run-table row for the given run.

    Used by ``upsert_run()`` for O(1) single-run persistence.

    Args:
        run: The run object (RunOutput, TeamRunOutput, WorkflowRunOutput) or dict.
        session_id: The session ID this run belongs to.
        user_id: Optional user ID to associate with the run.
        run_index: Explicit index within the session. Callers **must** supply
            this for INSERTS (any first-time save of a ``run_id``). For UPDATES
            to an existing row it may be ``None``; every adapter's
            ``on_conflict_do_update`` deliberately excludes ``run_index`` from
            the update set to preserve ordering. Omitting ``run_index`` on an
            INSERT silently writes NULL, which corrupts ``ORDER BY run_index``
            reads.

    Returns:
        Row dict matching the runs table schema.
    """
    current_time = int(time.time())
    run_id = run.get("run_id") if isinstance(run, dict) else getattr(run, "run_id", None)
    if run_id is None:
        raise ValueError("Run must have a run_id")

    run_data = run if isinstance(run, dict) else run.to_dict()

    # For run_index: use explicit param > run_data value > None
    effective_run_index = run_index
    if effective_run_index is None:
        effective_run_index = run_data.get("run_index")

    return {
        "run_id": run_id,
        "session_id": session_id,
        "run_type": get_run_type(run),
        "agent_id": run_data.get("agent_id"),
        "team_id": run_data.get("team_id"),
        "workflow_id": run_data.get("workflow_id"),
        "user_id": user_id,
        "parent_run_id": run_data.get("parent_run_id"),
        "status": run_data.get("status"),
        "run_index": effective_run_index,
        "run_data": run_data,
        "created_at": run_data.get("created_at") or current_time,
        "updated_at": current_time,
    }


# Run statuses (as stored string values) excluded from context/history reads.
# Derived from the single source of truth in ``agno.run.base`` so a DB-side
# "most recent N runs" fetch returns the same runs the in-memory history builder
# (``get_messages``) would — it filters these out *before* slicing the last N.
HISTORY_SKIP_STATUSES: List[str] = [status.value for status in _RUN_HISTORY_SKIP_STATUSES]


def filter_context_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only top-level, context-relevant runs from a list of run dicts.

    Drops member sub-runs (``parent_run_id`` set) and terminal-skip statuses,
    mirroring the pre-slice filtering in ``get_messages``. Used on the
    un-migrated / legacy-blob read path so slicing to "most recent N" yields the
    same window as the fully-migrated (SQL-filtered) path.
    """
    kept: List[Dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("parent_run_id") is not None:
            continue
        if run.get("status") in HISTORY_SKIP_STATUSES:
            continue
        kept.append(run)
    return kept


def merge_runs_table_with_legacy_blob(
    table_runs: List[Dict[str, Any]],
    legacy_runs: Optional[List[Any]],
) -> List[Dict[str, Any]]:
    """Merge runs fetched from the runs table with the legacy ``runs`` JSON blob.

    Used by adapter reads when a session may have its run history split across
    the new ``agno_runs`` table and the legacy ``agno_sessions.runs`` column
    (e.g. when the v3.0.0 migration has not yet been applied to that session).

    Ordering guarantee: chronological insertion order is preserved. The legacy
    blob is the historical order (v2.x wrote runs into that list in insertion
    order), so we walk it first and substitute the table's version whenever a
    run_id exists in both. Any runs that only exist in the table (writes made
    after migration nulled the blob for this session) are appended after the
    legacy-known runs, in the order the table returns them.

    Conflict resolution: the runs table wins on run_id conflicts (it's the
    source of truth for state changes like paused → completed).

    Args:
        table_runs: Rows fetched from the runs table (in insertion order —
            adapters sort by ``run_index`` then ``created_at``).
        legacy_runs: The raw value of the legacy ``runs`` column (may be a
            list, a JSON-encoded string, or ``None``).

    Returns:
        Merged list of run dicts in chronological insertion order. Empty if
        both inputs are empty.
    """
    if isinstance(legacy_runs, str):
        try:
            legacy_runs = json.loads(legacy_runs)
        except (json.JSONDecodeError, TypeError):
            log_warning("Could not parse legacy runs blob during merge; ignoring it")
            legacy_runs = None

    if not legacy_runs:
        return list(table_runs)

    # Index the table rows by run_id so we can substitute in O(1) while
    # walking the legacy order.
    table_by_id: Dict[Any, Dict[str, Any]] = {}
    for run in table_runs:
        if not isinstance(run, dict):
            continue
        rid = run.get("run_id")
        if rid is not None:
            table_by_id[rid] = run

    legacy_ids: set = set()
    merged: List[Dict[str, Any]] = []

    # Phase 1: walk the legacy blob in its stored (insertion) order. For each
    # id, prefer the table's copy when it exists so state changes since
    # migration are visible; fall back to the legacy copy otherwise.
    for legacy_run in legacy_runs:
        if not isinstance(legacy_run, dict):
            continue
        rid = legacy_run.get("run_id")
        if rid is None:
            continue
        legacy_ids.add(rid)
        merged.append(table_by_id.get(rid, legacy_run))

    # Phase 2: append any table-only runs (added after migration) in the order
    # the table returned them — these are strictly newer than everything the
    # blob knew about.
    for table_run in table_runs:
        if not isinstance(table_run, dict):
            continue
        rid = table_run.get("run_id")
        if rid is None or rid in legacy_ids:
            continue
        merged.append(table_run)

    return merged


def get_metrics_legacy_runs(sessions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The runs kept in the legacy runs field of the given sessions, as runs table records."""
    legacy_runs = []
    for session in sessions:
        # Parsed as merge_runs_table_with_legacy_blob parses it, skipping what is no run, as the migration does
        for run in merge_runs_table_with_legacy_blob([], session.get("runs")):
            # A legacy run is dated and typed the way the v3.0.0 migration writes it to the runs table
            if run.get("agent_id"):
                run_type = "agent"
            elif run.get("team_id"):
                run_type = "team"
            else:
                run_type = "workflow"
            legacy_runs.append(
                {
                    # As text, the way the runs table stores it
                    "run_id": str(run["run_id"]),
                    "session_id": session.get("session_id"),
                    "run_type": run_type,
                    "agent_id": run.get("agent_id"),
                    "team_id": run.get("team_id"),
                    "workflow_id": run.get("workflow_id"),
                    "user_id": session.get("user_id"),
                    "parent_run_id": run.get("parent_run_id"),
                    "status": run.get("status"),
                    "run_data": run,
                    "created_at": run.get("created_at") or session.get("created_at"),
                }
            )
    return legacy_runs


async def resolve_session_type(
    db: Union["BaseDb", "AsyncBaseDb"],
    session_id: str,
    session_type: Optional["SessionType"],
    user_id: Optional[str] = None,
) -> Tuple[Optional["SessionType"], Optional[Any]]:
    """Resolve session type by auto-detecting from DB if not provided.

    Args:
        db: Database adapter instance (sync or async).
        session_id: The session ID to look up.
        session_type: The session type if already known. If None, auto-detects from DB.
        user_id: Optional user ID filter.

    Returns:
        Tuple of (resolved_type, raw_session):
        - If session_type is already set: (session_type, None) — no DB fetch needed.
        - If session_type is None and session found: (detected_type, raw_dict).
        - If session_type is None and session not found: (None, None).
    """
    if session_type is not None:
        return session_type, None

    from agno.db.base import AsyncBaseDb, SessionType

    if isinstance(db, AsyncBaseDb):
        raw = await db.get_session(session_id=session_id, user_id=user_id, deserialize=False)
    else:
        raw = db.get_session(session_id=session_id, user_id=user_id, deserialize=False)

    if not raw:
        return None, None

    detected = detect_session_type(raw if isinstance(raw, dict) else {})
    resolved = SessionType(detected)
    return resolved, raw


def validate_pagination(limit: Optional[int], page: Optional[int]) -> None:
    """Validate a ``(limit, page)`` pair coming from a public read API.

    ``page`` is meaningless without ``limit`` — every adapter's pagination
    block is guarded by ``if limit is not None: if page is not None: ...``,
    so a caller who passes ``page=5`` and forgets ``limit`` gets **all rows**
    back instead of page 5 of some default size, silently. That's a bug
    with real fallout (wrong data surfaced, excess memory/bandwidth); raise
    at the boundary rather than paper over it.

    Passing neither is fine (no pagination). Passing ``limit`` without
    ``page`` is fine (first-N behavior). Passing ``page < 1`` is a caller
    bug (pages are 1-indexed).
    """
    if page is not None and limit is None:
        raise ValueError(
            "`page` was provided without `limit`. Pass both to paginate, "
            "or neither to fetch all rows. Silently returning everything on "
            "a paginated call hides caller bugs and surfaces wrong data."
        )
    if page is not None and page < 1:
        raise ValueError(f"`page` must be >= 1 (pages are 1-indexed); got {page}.")


# Table types MigrationManager.up() knows how to migrate at all, across every
# version it ships, not just the ones with a pending step in the current
# release: a sessions table still at its 2.0 shape needs the 2.3/2.5 steps even
# though 3.0 adds none. Must stay in sync with ``_table_type_to_attr`` in
# agno/db/migrations/manager.py, which cannot be imported here: manager ->
# db.base -> this module would be a cycle.
MIGRATABLE_TABLE_TYPES = frozenset(
    {
        "memories",
        "sessions",
        "metrics",
        "evals",
        "knowledge",
        "approvals",
        "components",
        "schedules",
        "schedule_runs",
        "learnings",
    }
)


def bound_index_name(db_type: str, index_name: str) -> str:
    """The index or table name as the server stores it, safe to bind in the existence check.

    Postgres folds identifiers longer than 63 bytes down to 63, so a constructed key name
    past the limit is stored truncated. psycopg truncates the over-long parameter the same
    way on the cast to ``name``, but asyncpg's binary protocol refuses it outright.
    """
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        return index_name[:63]
    return index_name


def table_schema_mismatch_error(table_ref: str, table_type: Optional[str] = None) -> SchemaMismatchError:
    """Build the error raised when an existing table fails schema validation.

    For table types MigrationManager can handle, the most common cause is an
    upgrade across Agno versions whose migrations have not been applied yet
    (e.g. v2.x data with a v3.x install), so the result is a
    ``MigrationRequiredError`` whose message points the user at the migration
    path instead of dead-ending. Other table types have no pending migrations,
    so migration advice would send the user in a circle; they get a plain
    ``SchemaMismatchError`` with repair guidance instead.
    """
    message = (
        f"Table {table_ref} has an invalid schema: it does not match what this version of Agno "
        "expects (see the warning or error logged above for details). "
    )
    if table_type is None or table_type in MIGRATABLE_TABLE_TYPES:
        message += (
            "If this database was created by an older version of Agno, apply the pending "
            "migrations with `asyncio.run(MigrationManager(db).up())` (import it from "
            "`agno.db.migrations.manager`; await the call directly in async code), or via the "
            "AgentOS endpoint `POST /databases/all/migrate`."
        )
        return MigrationRequiredError(table_name=table_ref, message=message)
    message += (
        "No Agno migration covers this table, so it was likely created or modified outside "
        "Agno. Compare it against the expected schema and repair it, or move Agno to a new "
        "table name so the table is recreated."
    )
    return SchemaMismatchError(table_name=table_ref, message=message)


def metric_record_day(record: Dict[str, Any]) -> Optional[date]:
    """Read the day off a stored metric record, or ``None`` if it has no usable one.

    Key-value backends store the date as an ISO string; an unparseable one is skipped
    rather than raised, so one bad row cannot break every metrics read.
    """
    raw = record.get("date")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return datetime.fromisoformat(raw).date()  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log_warning(f"Skipping metrics record {record.get('id')}: date {raw!r} is not a day")
        return None


def deserialize_metrics_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Read the rows of a metrics file with their date a date, as a JSON file keeps it as text."""
    deserialized_rows = []
    for row in rows:
        try:
            deserialized_rows.append({**row, "date": date.fromisoformat(row.get("date"))})  # type: ignore[arg-type]
        except (TypeError, ValueError):
            log_warning(f"Skipping metrics record {row.get('id')}: date {row.get('date')!r} is not a day")
    return deserialized_rows


def get_metrics_records_by_day(
    records: Sequence[Dict[str, Any]], start_timestamp: int, end_timestamp: int
) -> Dict[date, List[Dict[str, Any]]]:
    """The sessions or runs created in the given time range, by the UTC day they were created on.

    Args:
        records (Sequence[Dict[str, Any]]): The sessions or the runs.
        start_timestamp (int): The start of the range, included.
        end_timestamp (int): The end of the range, not included.

    Returns:
        Dict[date, List[Dict[str, Any]]]: The records of each day that has any.
    """
    records_by_day: Dict[date, List[Dict[str, Any]]] = {}
    for record in records:
        created_at = record.get("created_at") or 0
        if start_timestamp <= created_at < end_timestamp:
            day = datetime.fromtimestamp(created_at, tz=timezone.utc).date()
            records_by_day.setdefault(day, []).append(record)
    return records_by_day


def _metric_day(record: Dict[str, Any]) -> Optional[date]:
    """The day a metric record covers, whatever shape the backend stored it in.

    It arrives as a date, a datetime, an ISO string or an epoch second, and a record whose
    date is none of those is skipped rather than raised on.
    """
    day = record.get("date")
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    if isinstance(day, str):
        try:
            return datetime.fromisoformat(day).date()
        except ValueError:
            return None
    # bool is an int, and a record holding True would otherwise read as 1 January 1970
    if isinstance(day, (int, float)) and not isinstance(day, bool):
        return datetime.fromtimestamp(day, tz=timezone.utc).date()
    return None


def metric_bucket_key(record: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """The (day, period) a metric record belongs to, or ``None`` if its date is not a day.

    A period-less record belongs in the daily bucket.
    """
    day = _metric_day(record)
    if day is None:
        return None
    return (day.isoformat(), record.get("aggregation_period") or "daily")


def is_legacy_metric(record: Dict[str, Any]) -> bool:
    """Whether a record predates per-user buckets, so it holds every user's traffic."""
    # Such a record carries no owner at all, or the unowned sentinel it was stamped with, and
    # it counted its users; a real unowned bucket has no owner to count and stays at zero
    return "user_id" not in record or (not record["user_id"] and bool(record.get("users_count")))


def drop_legacy_metrics(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop the pre-user_id record for any bucket the per-user records already cover.

    That record holds the whole day's traffic for every user, so summing it alongside the
    per-user records counts the day twice. It only goes where per-user records for the same
    bucket exist to replace it; on its own it is still the only record of that day.
    """
    per_user_buckets = set()
    is_legacy = []
    for record in records:
        legacy = is_legacy_metric(record)
        is_legacy.append(legacy)
        if not legacy:
            per_user_buckets.add(metric_bucket_key(record))

    return [
        record
        for record, legacy in zip(records, is_legacy)
        if not legacy or metric_bucket_key(record) not in per_user_buckets
    ]


_METRIC_COUNT_FIELDS = (
    "agent_sessions_count",
    "team_sessions_count",
    "workflow_sessions_count",
    "agent_runs_count",
    "team_runs_count",
    "workflow_runs_count",
    "users_count",
)


def _merge_model_metrics(target: List[dict], extra: List[dict]) -> None:
    """Merge extra model_metrics into target in place, summing counts and costs per model."""
    index: Dict[Any, dict] = {}
    for m in [*target, *extra]:
        key = (m.get("model_id"), m.get("model_provider"))
        entry = index.get(key)
        if entry is None:
            index[key] = dict(m)
        else:
            entry["count"] = (entry.get("count") or 0) + (m.get("count") or 0)
            if m.get("cost") is not None:
                entry["cost"] = (entry.get("cost") or 0) + m["cost"]
    target[:] = list(index.values())


def _merge_timestamp(current: Any, candidate: Any, *, latest: bool) -> Any:
    """Merge two timestamps into the later (or earlier) one, tolerating None."""
    if candidate is None:
        return current
    if current is None:
        return candidate
    try:
        if latest:
            return candidate if candidate > current else current
        return candidate if candidate < current else current
    except TypeError:
        # Adapters store epoch ints; a row carrying a datetime cannot be ordered against one.
        return current


def aggregate_metrics_by_date(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse per-user metric rows into one aggregate row per date and period.

    Every reader that reports a day rather than a user needs this: stored rows are one per
    owner, so a day with three users arrives as three rows. The id is synthesised rather than
    carried over, because stored per-user ids embed the owner on most key-value backends and
    rows arrive in no particular order.
    """
    by_bucket: Dict[Any, dict] = {}
    for row in drop_legacy_metrics(rows):
        bucket = metric_bucket_key(row)
        if bucket is None:
            # The caller reports a day, so a record whose date is not one cannot be reported
            # at all. Skip it rather than fail every other user's row.
            log_warning(f"Skipping metrics record {row.get('id')}: date {row.get('date')!r} is not a day")
            continue
        day_key, period = bucket
        agg = by_bucket.get(bucket)
        if agg is None:
            agg = {**row, "id": f"{day_key}_{period}"}
            agg["token_metrics"] = dict(row.get("token_metrics") or {})
            agg["model_metrics"] = [dict(m) for m in (row.get("model_metrics") or [])]
            by_bucket[bucket] = agg
            continue
        for field in _METRIC_COUNT_FIELDS:
            agg[field] = (agg.get(field) or 0) + (row.get(field) or 0)
        for token, value in (row.get("token_metrics") or {}).items():
            if token == "cost":
                # A cost no run reported stays None, not 0
                if value is not None:
                    agg["token_metrics"][token] = (agg["token_metrics"].get(token) or 0) + value
            else:
                agg["token_metrics"][token] = (agg["token_metrics"].get(token) or 0) + (value or 0)
        _merge_model_metrics(agg["model_metrics"], row.get("model_metrics") or [])
        agg["created_at"] = _merge_timestamp(agg.get("created_at"), row.get("created_at"), latest=False)
        agg["updated_at"] = _merge_timestamp(agg.get("updated_at"), row.get("updated_at"), latest=True)
    return list(by_bucket.values())


def identify_metrics_by_owner(rows: Sequence[Dict[str, Any]], user_id: str) -> List[Dict[str, Any]]:
    """Give one owner's rows the same id on every backend.

    Stored ids are the backend's own: a uuid on the SQL adapters, an owner-bearing string on
    the key-value ones. Handing those out makes the field mean something different per
    deployment, and on some backends puts the owner inside it. A row whose date is not a day
    keeps the id it was stored with, there being no bucket to name it after.
    """
    identified: List[Dict[str, Any]] = []
    for row in rows:
        bucket = metric_bucket_key(row)
        if bucket is None:
            identified.append(dict(row))
            continue
        day_key, period = bucket
        identified.append({**row, "id": f"{day_key}_{user_id}_{period}"})
    return identified


def list_metrics_models(model_metrics: Dict[str, Dict[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """List the models of a model_metrics map as agno_metrics lists them: one entry per model and provider, with its
    count and its cost, sorted by model and provider."""
    return sorted(
        (
            {"model_id": model_id, "model_provider": provider, "count": model["count"], "cost": model.get("cost")}
            for provider, models in model_metrics.items()
            for model_id, model in models.items()
        ),
        key=lambda model: (model["model_id"], model["model_provider"]),
    )


def list_metrics_totals_models(totals: Dict[str, Any]) -> Dict[str, Any]:
    """Totals with their model_metrics listed by list_metrics_models, as get_component_metrics returns them."""
    if "model_metrics" not in totals:
        return totals
    return {**totals, "model_metrics": list_metrics_models(totals["model_metrics"])}


# The periods a row of agno_aggregate_metrics covers. A month row is dated the first day of
# its month.
_METRICS_PERIODS = ("daily", "monthly")

# What a row of agno_component_metrics is counted under, by the type of the session or run.
METRICS_COMPONENT_TYPES = ("agent", "team", "workflow")

# The columns a row of agno_component_metrics is unique by, and a row of agno_aggregate_metrics. An aggregate metrics
# row with user_id "" is the everyone row, which adds up every run, runs with no user included.
COMPONENT_METRICS_KEY_COLUMNS = (
    "aggregation_period",
    "date",
    "user_id",
    "component_type",
    "component_id",
    "parent_component_id",
    "root_component_id",
)
AGGREGATE_METRICS_KEY_COLUMNS = ("aggregation_period", "date", "user_id")

# The id of the one row of agno_metrics_refreshes, which one refresh at a time holds.
METRICS_REFRESH_ID = "metrics"

# Every token count a model call reports, the fields of BaseMetrics.
METRICS_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "audio_input_tokens",
    "audio_output_tokens",
    "audio_total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)

# The token counts kept as the keys of one JSON column, token_details, instead of a column each. The audio total,
# audio_total_tokens, is not kept: a read adds it up from the audio counts.
METRICS_TOKEN_DETAILS_FIELDS = ("cache_read_tokens", "cache_write_tokens", "audio_input_tokens", "audio_output_tokens")

# The cost of a row's runs, also kept in token_details: the total cost of the runs, and of a session's manual
# compactions, that reported one, and how many runs did. A row none of whose runs reported a cost keeps neither.
METRICS_COST_FIELDS = ("cost", "cost_runs_count")

# The upper bounds, in milliseconds, of the buckets each timing is counted into. They never change: buckets counted
# under different bounds cannot be added up.
_METRICS_BUCKET_BOUNDS_MS = (
    10,
    12,
    15,
    20,
    25,
    30,
    40,
    50,
    60,
    80,
    100,
    120,
    150,
    200,
    250,
    300,
    400,
    500,
    600,
    800,
    1000,
    1200,
    1500,
    2000,
    2500,
    3000,
    4000,
    5000,
    6000,
    8000,
    10000,
    12000,
    15000,
    20000,
    25000,
    30000,
    40000,
    50000,
    60000,
    80000,
    100000,
    120000,
    150000,
    200000,
    250000,
    300000,
    400000,
    500000,
    600000,
    800000,
    1000000,
    1200000,
    1500000,
    2000000,
    2500000,
    3000000,
    4000000,
    5000000,
    6000000,
    8000000,
)

# Rows a rebuild reads at a time, so a day or a month of many rows is never held or decoded in one step.
METRICS_BATCH_SIZE = 1000

# A lock goes stale 300 s after its last heartbeat by the database's clock, and every day heartbeats it, so a process
# that stopped while holding the metrics refresh never holds it longer.
METRICS_LOCK_SECONDS = 300

# A write checks whether it reopens a day before it commits, so a write checked before midnight can commit after it; a
# day is completed 600 s after the point that write could have reopened it, so a calculation never completes it first.
METRICS_DAY_GRACE_SECONDS = 600

# A metrics write another process changed since it was read is read and written again, up to this many times, as the
# file and memory stores have no transaction or row lock and DynamoDB writes the everyone row on a version condition.
METRICS_WRITE_RETRIES = 5

METRICS_STOPPED_ERROR = "The metrics refresh stopped before it finished"

# Each timing a row keeps: how many were counted, their total and their maximum in milliseconds,
# and their buckets.
_METRICS_TIMINGS = {
    "duration": ("duration_runs_count", "total_duration_ms", "max_duration_ms", "duration_buckets"),
    "time_to_first_token": (
        "time_to_first_token_runs_count",
        "total_time_to_first_token_ms",
        "max_time_to_first_token_ms",
        "time_to_first_token_buckets",
    ),
    "model_call": ("model_calls_count", "total_model_call_ms", "max_model_call_ms", "model_call_buckets"),
}

# The columns of a row that are added up, the ones that keep the largest value, and the JSON maps
# of counts.
METRICS_SUM_COLUMNS = (
    "sessions_count",
    "runs_count",
    *[field for field in METRICS_TOKEN_FIELDS if field not in [*METRICS_TOKEN_DETAILS_FIELDS, "audio_total_tokens"]],
    "duration_runs_count",
    "time_to_first_token_runs_count",
    "model_calls_count",
    "total_duration_ms",
    "total_time_to_first_token_ms",
    "total_model_call_ms",
)
METRICS_MAX_COLUMNS = ("max_duration_ms", "max_time_to_first_token_ms", "max_model_call_ms")
METRICS_COUNT_MAP_COLUMNS = (
    "status_metrics",
    "duration_buckets",
    "time_to_first_token_buckets",
    "model_call_buckets",
    "token_details",
)

# The columns of a row that are totalled.
METRICS_FIELDS = (
    *METRICS_SUM_COLUMNS,
    *METRICS_MAX_COLUMNS,
    *METRICS_COUNT_MAP_COLUMNS,
    "model_metrics",
    "tool_metrics",
    "additional_metrics",
)

# Every field that is added up: the columns, the runs no other run started, and the token counts and cost of
# token_details.
METRICS_SUM_FIELDS = (
    *METRICS_SUM_COLUMNS,
    "root_runs_count",
    *METRICS_TOKEN_DETAILS_FIELDS,
    "audio_total_tokens",
    *METRICS_COST_FIELDS,
)

# What get_component_metrics can total, and totals when the caller names none: every column but token_details, whose
# token counts and cost are totalled one by one, with the runs no other run started in place of every run.
METRICS_READ_FIELDS = (
    *["root_runs_count" if field == "runs_count" else field for field in METRICS_FIELDS if field != "token_details"],
    *METRICS_TOKEN_DETAILS_FIELDS,
    "audio_total_tokens",
    *METRICS_COST_FIELDS,
)

# The counts a row of agno_aggregate_metrics keeps beside the columns of agno_component_metrics, as agno_metrics
# keeps them.
AGGREGATE_METRICS_COUNT_COLUMNS = _METRIC_COUNT_FIELDS


def resolve_metrics_fields(fields: Optional[Sequence[str]]) -> List[str]:
    """The columns a get_component_metrics call totals, rejecting any the table does not have."""
    if fields is None:
        return list(METRICS_READ_FIELDS)
    unknown = [field for field in fields if field not in METRICS_READ_FIELDS]
    if unknown:
        raise ValueError(f"Unknown metrics fields: {unknown}")
    return list(fields)


def empty_metrics_totals(fields: Sequence[str] = METRICS_FIELDS) -> Dict[str, Any]:
    """The totals of no row: zero counts, no maximum and no cost, empty maps and no models."""
    totals: Dict[str, Any] = {}
    for field in fields:
        if field in METRICS_MAX_COLUMNS or field == "cost":
            totals[field] = None
        elif field in METRICS_SUM_FIELDS:
            totals[field] = 0
        else:
            totals[field] = {}
    return totals


def _empty_metrics_tool_totals() -> Dict[str, Any]:
    """The totals of one tool in tool_metrics before any call: no calls, no failures and no timing."""
    return {"count": 0, "failed_count": 0, "total_ms": 0, "max_ms": None, "buckets": {}}


def add_metrics_totals(target: Dict[str, Any], extra: Dict[str, Any], fields: Sequence[str] = METRICS_FIELDS) -> None:
    """Add the totals of extra to target in place.

    Counts and maps are summed, maximums keep the larger value, a cost no run reported stays None, and
    additional_metrics is merged the way RunMetrics.additional_metrics is.
    """
    for field in fields:
        value = extra.get(field)
        # Nothing to add: a zero count, no maximum or an empty map leaves the total as it is, but a cost of 0 is added
        if field in target and (value is None or (not value and field not in METRICS_MAX_COLUMNS and field != "cost")):
            continue
        if field == "cost":
            if value is not None:
                target[field] = (target.get(field) or 0) + value
        elif field in METRICS_SUM_FIELDS:
            target[field] = (target.get(field) or 0) + (value or 0)
        elif field in METRICS_MAX_COLUMNS:
            if value is not None and (target.get(field) is None or value > target[field]):
                target[field] = value
        elif field == "model_metrics":
            # Each provider's models, counted and costed per model
            model_metrics = {
                provider: {model_id: dict(model) for model_id, model in models.items()}
                for provider, models in (target.get(field) or {}).items()
            }
            for provider, models in (value or {}).items():
                provider_models = model_metrics.setdefault(provider, {})
                for model_id, model in models.items():
                    model_totals = provider_models.setdefault(model_id, {"count": 0})
                    model_totals["count"] += model.get("count") or 0
                    if model.get("cost") is not None:
                        model_totals["cost"] = (model_totals.get("cost") or 0) + model["cost"]
            target[field] = model_metrics
        elif field == "tool_metrics":
            # Each toolkit's tools, with their calls, failures and timings per tool
            tool_metrics = {
                toolkit: {
                    tool_name: {**tool, "buckets": dict(tool.get("buckets") or {})} for tool_name, tool in tools.items()
                }
                for toolkit, tools in (target.get(field) or {}).items()
            }
            for toolkit, tools in (value or {}).items():
                toolkit_tools = tool_metrics.setdefault(toolkit, {})
                for tool_name, tool in tools.items():
                    tool_totals = toolkit_tools.setdefault(tool_name, _empty_metrics_tool_totals())
                    for key in ("count", "failed_count", "total_ms"):
                        tool_totals[key] += tool.get(key) or 0
                    if tool.get("max_ms") is not None and (
                        tool_totals["max_ms"] is None or tool["max_ms"] > tool_totals["max_ms"]
                    ):
                        tool_totals["max_ms"] = tool["max_ms"]
                    for bucket, count in (tool.get("buckets") or {}).items():
                        tool_totals["buckets"][bucket] = tool_totals["buckets"].get(bucket, 0) + (count or 0)
            target[field] = tool_metrics
        elif field == "additional_metrics":
            # Merge additional_metrics (sum numeric values, keep latest for others)
            additional_metrics = dict(target.get(field) or {})
            for key, metric in (value or {}).items():
                if (
                    key in additional_metrics
                    and isinstance(metric, (int, float))
                    and isinstance(additional_metrics[key], (int, float))
                ):
                    additional_metrics[key] += metric
                else:
                    additional_metrics[key] = metric
            target[field] = additional_metrics
        else:
            counts = dict(target.get(field) or {})
            for key, count in (value or {}).items():
                counts[key] = counts.get(key, 0) + (count or 0)
            target[field] = counts


def merge_metrics_totals(totals: Sequence[Dict[str, Any]], fields: Sequence[str]) -> Dict[str, Any]:
    """Merge the metrics totals of several dates or databases into one set of totals."""
    merged = empty_metrics_totals(fields)
    for extra in totals:
        add_metrics_totals(merged, extra, fields)
    return merged


def _metrics_component(record: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """The component_type and component_id a session or run is counted under, by its type.

    ``None`` for a type that is no agent, team or workflow, which no row can be kept under.
    """
    component_type = record.get("session_type") or record.get("run_type")
    if component_type not in METRICS_COMPONENT_TYPES:
        record_id = record.get("run_id") or record.get("session_id")
        log_warning(f"Skipping metrics record {record_id}: type {component_type!r} is not an agent, team or workflow")
        return None
    return component_type, record.get(f"{component_type}_id") or ""


def _metrics_parent_component_id(run: Dict[str, Any], components: Dict[str, Tuple[str, str]]) -> str:
    """The id of the agent, team or workflow whose run started the given run.

    Empty for a run no run started.
    """
    _, component_id = components.get(run.get("parent_run_id") or "", ("", ""))
    return component_id


def metrics_parent_run_id(run: Dict[str, Any]) -> Optional[str]:
    """The id of the run that started a stored run: its team's or workflow's run, or the run whose tool call started
    it."""
    return run.get("parent_run_id") or (run.get("run_data") or {}).get("called_from_run_id")


def get_metrics_runs(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The stored runs as component metrics count them, each with the id of the run that started it."""
    return [{**row, "parent_run_id": metrics_parent_run_id(row)} for row in rows]


def _get_metrics_parent_runs(runs_by_id: Dict[str, Dict[str, Any]], parent_run_ids: List[str]) -> List[Dict[str, Any]]:
    """The stored runs that started the given runs, and the runs that started those, up to the whole run."""
    parent_runs: List[Dict[str, Any]] = []
    seen_run_ids: Set[str] = set()
    while parent_run_ids:
        seen_run_ids.update(parent_run_ids)
        parent_runs.extend(runs_by_id[run_id] for run_id in parent_run_ids if run_id in runs_by_id)
        parent_run_ids = sorted(
            {run["parent_run_id"] for run in parent_runs if run.get("parent_run_id")} - seen_run_ids
        )
    return parent_runs


def _metrics_root_component_id(
    run: Dict[str, Any], components: Dict[str, Tuple[str, str]], parent_run_ids: Dict[str, str]
) -> str:
    """The id of the agent, team or workflow whose run started the whole run the given run is part of.

    The run's own component id for a run no run started.
    """
    run_id = run["run_id"]
    seen_run_ids = {run_id}
    # A parent run that is not stored ends the walk, as it does for parent_component_id
    while parent_run_ids.get(run_id) in components and parent_run_ids[run_id] not in seen_run_ids:
        run_id = parent_run_ids[run_id]
        seen_run_ids.add(run_id)
    _, component_id = components[run_id]
    return component_id


def _metrics_nested_runs(run_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The runs nested inside a stored run: its workflow steps' runs, its team members' runs and its workflow
    agent's run."""
    workflow_agent_run = run_data.get("workflow_agent_run")
    return (
        (run_data.get("step_executor_runs") or [])
        + (run_data.get("member_responses") or [])
        + ([workflow_agent_run] if workflow_agent_run else [])
    )


def _add_metrics_nested_run_ids(run_data: Dict[str, Any], nested_run_ids: Set[str]) -> None:
    """Add the ids of every run nested inside run_data, at any depth, to nested_run_ids."""
    for nested_run in _metrics_nested_runs(run_data):
        if nested_run.get("run_id"):
            nested_run_ids.add(nested_run["run_id"])
        _add_metrics_nested_run_ids(nested_run, nested_run_ids)


def _add_metrics_remote_member_runs(
    run_data: Dict[str, Any],
    session_id: Optional[str],
    remote_parent_run_ids: Dict[str, str],
    remote_session_ids: Set[str],
) -> None:
    """Add the remote members' runs nested inside run_data, at any depth: each run's parent, and its session."""
    for nested_run in _metrics_nested_runs(run_data):
        nested_session_id = nested_run.get("session_id") or ""
        # A remote member runs in a session of its own, named after its team's session and the member
        if session_id and nested_session_id.startswith(f"{session_id}:"):
            if nested_run.get("run_id") and nested_run.get("parent_run_id"):
                remote_parent_run_ids[nested_run["run_id"]] = nested_run["parent_run_id"]
            remote_session_ids.add(nested_session_id)
        _add_metrics_remote_member_runs(
            nested_run, nested_session_id or session_id, remote_parent_run_ids, remote_session_ids
        )


def metrics_nested_run_ids(runs: Sequence[Dict[str, Any]]) -> Set[str]:
    """The ids of every run nested inside a day's stored runs, at any depth, and of the member run each sandboxed
    member's record of the day repeats.

    A nested run ending after midnight is stored on the next day, so the rollup asks the runs table
    which of these ids exist before it walks the nested runs.
    """
    nested_run_ids: Set[str] = set()
    for run in runs:
        _add_metrics_nested_run_ids(run.get("run_data") or {}, nested_run_ids)
        run_id = run.get("run_id") or ""
        if run_id.endswith(".sandbox"):
            nested_run_ids.add(run_id[: -len(".sandbox")])
    return nested_run_ids


def metrics_remote_member_team_session_ids(runs: Sequence[Dict[str, Any]]) -> Set[str]:
    """The team sessions of the remote members' runs of a day that no run of the day names.

    A team run started before midnight is stored on the day before its remote member's run, so the rollup reads that
    day's runs of these sessions too.
    """
    remote_parent_run_ids: Dict[str, str] = {}
    for run in runs:
        _add_metrics_remote_member_runs(run.get("run_data") or {}, run.get("session_id"), remote_parent_run_ids, set())
    team_session_ids: Set[str] = set()
    for run in runs:
        session_id = run.get("session_id") or ""
        member_id = run.get(f"{run.get('run_type')}_id") or ""
        # A remote member runs in a session named after its team's session and the member
        if (
            not run.get("parent_run_id")
            and run.get("run_id") not in remote_parent_run_ids
            and member_id
            and len(session_id) > len(member_id) + 1
            and session_id.endswith(f":{member_id}")
        ):
            team_session_ids.add(session_id[: -len(member_id) - 1])
    return team_session_ids


def _metrics_runs(run_data: Dict[str, Any], seen_run_ids: Set[str]) -> List[Dict[str, Any]]:
    """A stored run and every run nested inside it, skipping nested runs already counted."""
    runs = [run_data]
    for nested_run in _metrics_nested_runs(run_data):
        run_id = nested_run.get("run_id")
        if run_id in seen_run_ids:
            continue
        if run_id:
            seen_run_ids.add(run_id)
        runs.extend(_metrics_runs(nested_run, seen_run_ids))
    return runs


def _metrics_request_durations(call: Dict[str, Any]) -> List[float]:
    """How long each request of a model call took, in seconds.

    Messages carried over from an earlier run are skipped: those from history, and those a forked run copied from
    the run it was forked from.
    """
    return [
        message["metrics"]["duration"]
        for message in (call.get("messages") or [])[call.get("forked_from_message_index") or 0 :]
        if message.get("role") == "assistant"
        and not message.get("from_history")
        and (message.get("metrics") or {}).get("duration") is not None
    ]


def _metrics_model_provider(provider: str) -> str:
    """The provider a model is labelled by, as a run labels its own model, from the provider name its metrics details
    keep for the model's class: the OpenAI classes add " Chat" and " Responses" to it."""
    for suffix in (" Chat", " Responses"):
        if provider.endswith(suffix):
            return provider[: -len(suffix)]
    return provider


def _metrics_bucket(milliseconds: int) -> str:
    """The bucket a timing is counted into."""
    for bound in _METRICS_BUCKET_BOUNDS_MS:
        if milliseconds <= bound:
            return f"le_{bound}"
    return f"gt_{_METRICS_BUCKET_BOUNDS_MS[-1]}"


def metrics_percentile(buckets: Dict[str, int], fraction: float, max_ms: Optional[int] = None) -> Optional[int]:
    """The timing, in milliseconds, below which a fraction of the counted timings fall.

    It is read from bucket counts and placed inside its bucket in proportion to where the fraction
    lands, so it is approximate, and it never exceeds max_ms, the slowest timing counted.
    """
    total = sum(buckets.values())
    if not total:
        return None
    # One timing is its own median and p95, and the slowest timing recorded is exactly it
    if total == 1 and max_ms is not None:
        return max_ms
    target = fraction * total
    lower_bound = 0
    counted = 0
    for bound in _METRICS_BUCKET_BOUNDS_MS:
        count = buckets.get(f"le_{bound}", 0)
        if count and counted + count >= target:
            value = round(lower_bound + (bound - lower_bound) * (target - counted) / count)
            return value if max_ms is None else min(value, max_ms)
        counted += count
        lower_bound = bound
    # Past the last bound only the slowest timing recorded says how far the tail goes
    return _METRICS_BUCKET_BOUNDS_MS[-1] if max_ms is None else max(max_ms, _METRICS_BUCKET_BOUNDS_MS[-1])


def metrics_versions(rows: Sequence[Any]) -> Dict[str, int]:
    """The version of each aggregate metrics row, keyed by its aggregation period and date.

    Each row holds its aggregation_period, date and version.
    """
    return {f"{row.aggregation_period} {row.date.isoformat()}": row.version for row in rows}


def _add_metrics_timing(totals: Dict[str, Any], timing: str, seconds: Optional[float]) -> None:
    """Add one timing to a row: a count, a total and a maximum in milliseconds, and its bucket."""
    if seconds is None:
        return
    count_column, total_column, max_column, buckets_column = _METRICS_TIMINGS[timing]
    milliseconds = int(round(seconds * 1000))
    totals[count_column] += 1
    totals[total_column] += milliseconds
    totals[max_column] = milliseconds if totals[max_column] is None else max(totals[max_column], milliseconds)
    bucket = _metrics_bucket(milliseconds)
    totals[buckets_column][bucket] = totals[buckets_column].get(bucket, 0) + 1


def _add_metrics_tool_calls(totals: Dict[str, Any], run_data: Dict[str, Any]) -> None:
    """Add each tool call of a stored run to tool_metrics, under its toolkit, or "" for none, and its tool name."""
    # The tool calls answered in the first messages of a forked run, copies of the run it was forked from
    copied_tool_call_ids = {
        message["tool_call_id"]
        for message in (run_data.get("messages") or [])[: run_data.get("forked_from_message_index") or 0]
        if message.get("role") == "tool" and message.get("tool_call_id")
    }
    for tool_call in run_data.get("tools") or []:
        if not isinstance(tool_call, dict) or not tool_call.get("tool_name"):
            continue
        # A tool call still paused or rejected by the user never ran, and one a forked run copied counts on the run it
        # was forked from
        if (
            tool_call.get("requires_confirmation")
            or tool_call.get("requires_user_input")
            or tool_call.get("external_execution_required")
            or tool_call.get("confirmed") is False
            or tool_call.get("tool_call_id") in copied_tool_call_ids
        ):
            continue
        tool = (
            totals["tool_metrics"]
            .setdefault(tool_call.get("toolkit") or "", {})
            .setdefault(tool_call["tool_name"], _empty_metrics_tool_totals())
        )
        tool["count"] += 1
        if tool_call.get("tool_call_error"):
            tool["failed_count"] += 1
        seconds = (tool_call.get("metrics") or {}).get("duration")
        if seconds is None:
            continue
        milliseconds = int(round(seconds * 1000))
        tool["total_ms"] += milliseconds
        tool["max_ms"] = milliseconds if tool["max_ms"] is None else max(tool["max_ms"], milliseconds)
        bucket = _metrics_bucket(milliseconds)
        tool["buckets"][bucket] = tool["buckets"].get(bucket, 0) + 1


def _calculate_run_metrics(run: Dict[str, Any], seen_run_ids: Set[str]) -> Dict[str, Any]:
    """The totals one stored run adds to its row."""
    totals = empty_metrics_totals()
    status = run.get("status")
    run_data = run.get("run_data") or {}
    run_metrics = run_data.get("metrics") or {}

    # A new run replaced a regenerated run, so it is not counted, but its model calls still count
    if status != RunStatus.regenerated.value:
        totals["runs_count"] += 1
        if status:
            totals["status_metrics"][status] = 1
    if status == RunStatus.completed.value:
        _add_metrics_timing(totals, "duration", run_metrics.get("duration"))
        _add_metrics_timing(totals, "time_to_first_token", run_metrics.get("time_to_first_token"))

    for nested_run in _metrics_runs(run_data, seen_run_ids):
        # A run that records no model, such as an adapter's, still counts its tool calls
        _add_metrics_tool_calls(totals, nested_run)
        if not nested_run.get("model"):
            continue
        nested_run_metrics = nested_run.get("metrics") or {}
        for field in METRICS_TOKEN_FIELDS:
            tokens = int(nested_run_metrics.get(field) or 0)
            if field in METRICS_SUM_COLUMNS:
                totals[field] += tokens
            elif field in METRICS_TOKEN_DETAILS_FIELDS and tokens:
                totals["token_details"][field] = totals["token_details"].get(field, 0) + tokens
        if nested_run_metrics.get("cost") is not None:
            totals["token_details"]["cost"] = totals["token_details"].get("cost", 0) + nested_run_metrics["cost"]
            totals["token_details"]["cost_runs_count"] = totals["token_details"].get("cost_runs_count", 0) + 1
        # The rest a run reports beside its tokens, such as eval_duration, merged as RunMetrics merges it
        add_metrics_totals(totals, nested_run_metrics, ["additional_metrics"])
        for seconds in _metrics_request_durations(nested_run):
            _add_metrics_timing(totals, "model_call", seconds)

        details = nested_run_metrics.get("details")
        model_type_metrics_lists = [
            model_type_metrics
            for model_type_metrics in (details.values() if isinstance(details, dict) else [])
            if isinstance(model_type_metrics, list)
        ]
        # Each model labelled by its provider, as the run's own model is, not by the provider name details keep
        # for the model's class, such as "OpenAI Responses"
        provider_labels = {
            model_metrics.get("provider"): nested_run.get("model_provider") or ""
            for model_type_metrics in model_type_metrics_lists
            for model_metrics in model_type_metrics
            if isinstance(model_metrics, dict) and model_metrics.get("id") == nested_run["model"]
        }
        # The run's own model, as agno_metrics counted it whether or not it reported usage, and every other model it
        # used, such as its output model, once, each with the cost its details report for it
        nested_run_model = (nested_run["model"], nested_run.get("model_provider") or "")
        model_costs: Dict[Tuple[str, str], Optional[float]] = {nested_run_model: None}
        for model_type_metrics in model_type_metrics_lists:
            for model_metrics in model_type_metrics:
                if not isinstance(model_metrics, dict) or model_metrics.get("id") in (None, ""):
                    continue
                model = (
                    nested_run_model
                    if model_metrics["id"] == nested_run["model"]
                    else (
                        model_metrics["id"],
                        provider_labels.get(model_metrics.get("provider"))
                        or _metrics_model_provider(model_metrics.get("provider") or ""),
                    )
                )
                cost = model_costs.get(model)
                if model_metrics.get("cost") is not None:
                    cost = (cost or 0) + model_metrics["cost"]
                model_costs[model] = cost
        for (model_id, provider), cost in model_costs.items():
            model_totals = totals["model_metrics"].setdefault(provider, {}).setdefault(model_id, {"count": 0})
            model_totals["count"] += 1
            if cost is not None:
                model_totals["cost"] = (model_totals.get("cost") or 0) + cost
    return totals


def _calculate_session_compaction_metrics(session: Dict[str, Any]) -> Dict[str, Any]:
    """The totals a session's compaction metrics add to its row: the usage of a manual compaction no run carries."""
    totals = empty_metrics_totals()
    compaction_metrics = session.get("compaction_metrics") or {}
    if isinstance(compaction_metrics, str):
        try:
            compaction_metrics = json.loads(compaction_metrics)
        except (json.JSONDecodeError, TypeError):
            log_warning(f"Could not parse the compaction metrics of session {session.get('session_id')}; ignoring them")
            compaction_metrics = {}
    if not isinstance(compaction_metrics, dict):
        compaction_metrics = {}
    for field in METRICS_TOKEN_FIELDS:
        tokens = int(compaction_metrics.get(field) or 0)
        if field in METRICS_SUM_COLUMNS:
            totals[field] += tokens
        elif field in METRICS_TOKEN_DETAILS_FIELDS and tokens:
            totals["token_details"][field] = totals["token_details"].get(field, 0) + tokens
    if compaction_metrics.get("cost") is not None:
        totals["token_details"]["cost"] = totals["token_details"].get("cost", 0) + compaction_metrics["cost"]
    add_metrics_totals(totals, compaction_metrics, ["additional_metrics"])
    return totals


def calculate_date_component_metrics(
    date_to_process: date,
    sessions: List[Dict[str, Any]],
    runs: List[Dict[str, Any]],
    stored_run_ids: Set[str],
    parent_runs: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Calculate component metrics for the given single date, one row per user and agent, team or workflow.

    The runs another run of the date started are counted apart, under the id of what started
    them and of what started the whole run. The tokens of a run nested inside another, and not
    stored as a run of its own, are counted on the row of the run it is nested inside.

    Args:
        date_to_process (date): The date to calculate component metrics for.
        sessions (List[Dict[str, Any]]): The sessions created on that date, with the compaction metrics of their
            session_data.
        runs (List[Dict[str, Any]]): The runs created on that date, as stored.
        stored_run_ids (Set[str]): The ids of the nested runs of that date, and of the member runs its
            sandboxed members' records repeat, that are stored as runs of their own, on any date. Those
            are counted where they are stored.
        parent_runs (Sequence[Dict[str, Any]]): The runs of another date that started runs of
            that date, such as a team run started before midnight, and the runs that started those.
            Only their ids and parent ids are read, and the remote members' runs nested inside them.

    Returns:
        List[Dict[str, Any]]: The calculated rows of agno_component_metrics, one per user, agent, team or workflow,
            parent and root.
    """
    per_owner: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}

    # The AgentOS of a remote member stores its run with no parent; on a shared database its team's run names it
    remote_parent_run_ids: Dict[str, str] = {}
    remote_session_ids: Set[str] = set()
    for run in list(runs) + list(parent_runs):
        _add_metrics_remote_member_runs(
            run.get("run_data") or {}, run.get("session_id"), remote_parent_run_ids, remote_session_ids
        )

    for session in sessions:
        # A remote member's session holds a member run of its team's session
        if session.get("session_id") in remote_session_ids:
            continue
        metadata = session.get("metadata")
        # A harness agent run for a team or workflow keeps its native state in a session of its own, named after the
        # parent's session and the agent; the parent's session counts the conversation
        if (
            session.get("session_type") == "agent"
            and isinstance(metadata, dict)
            and metadata.keys() & {"team_id", "workflow_id"}
            and (session.get("session_id") or "").endswith(f":{session.get('agent_id')}")
        ):
            continue
        component = _metrics_component(session)
        if component is None:
            continue
        # A session is started by no run, so it is the root of its own runs
        bucket_key = (session.get("user_id") or "", *component, "", component[1])
        bucket = per_owner.setdefault(bucket_key, empty_metrics_totals())
        bucket["sessions_count"] += 1
        try:
            add_metrics_totals(bucket, _calculate_session_compaction_metrics(session))
        except (TypeError, ValueError, KeyError) as e:
            log_warning(f"Skipping metrics record {session.get('session_id')}: {e}")

    day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
    seen_run_ids = day_run_ids | stored_run_ids
    components = {
        run["run_id"]: component
        for run in list(runs) + list(parent_runs)
        if run.get("run_id") and (component := _metrics_component(run)) is not None
    }
    parent_run_ids = {
        run["run_id"]: run["parent_run_id"]
        for run in list(runs) + list(parent_runs)
        if run.get("run_id") and run.get("parent_run_id")
    }
    for run_id, parent_run_id in remote_parent_run_ids.items():
        parent_run_ids.setdefault(run_id, parent_run_id)
    for run in runs:
        if not run.get("parent_run_id") and run.get("run_id") in remote_parent_run_ids:
            run = {**run, "parent_run_id": remote_parent_run_ids[run["run_id"]]}
        # A run copied into a forked session repeats a run counted in the session it was made in
        if (run.get("run_data") or {}).get("forked_from_session_id"):
            continue
        # A sandboxed member's own record of a turn its team stores as the member run, on any day
        run_id = run.get("run_id") or ""
        if run_id.endswith(".sandbox") and run_id[: -len(".sandbox")] in seen_run_ids:
            continue
        component = components.get(run["run_id"]) if run.get("run_id") else _metrics_component(run)
        if component is None:
            continue
        try:
            run_totals = _calculate_run_metrics(run, seen_run_ids)
        except (TypeError, ValueError, KeyError) as e:
            log_warning(f"Skipping metrics record {run.get('run_id')}: {e}")
            continue
        root_component_id = (
            _metrics_root_component_id(run, components, parent_run_ids) if run.get("run_id") else component[1]
        )
        bucket_key = (
            run.get("user_id") or "",
            *component,
            _metrics_parent_component_id(run, components),
            root_component_id,
        )
        bucket = per_owner.setdefault(bucket_key, empty_metrics_totals())
        add_metrics_totals(bucket, run_totals)

    current_time = int(time.time())

    records: List[dict] = []
    for (user_id, component_type, component_id, parent_component_id, root_component_id), bucket in sorted(
        per_owner.items()
    ):
        records.append(
            {
                "aggregation_period": "daily",
                "date": date_to_process,
                "user_id": user_id,
                "component_type": component_type,
                "component_id": component_id,
                "parent_component_id": parent_component_id,
                "root_component_id": root_component_id,
                **bucket,
                "created_at": current_time,
                "updated_at": current_time,
            }
        )

    return records


def metrics_calculation_enabled() -> bool:
    """Whether metrics calculation is turned on by the metrics_calculation_enabled setting AgentOS reads, so the
    switch also stops the refresh on read of a database no AgentOS runs."""
    return getenv("METRICS_CALCULATION_ENABLED", "true").lower() in ("true", "1", "yes", "on", "y", "t")


def metrics_day_completed(day: date) -> bool:
    """Whether a day's metrics can be final.

    A run can be written again after its day ended, so a day is completed one day and METRICS_DAY_GRACE_SECONDS later.
    """
    now = datetime.now(timezone.utc) - timedelta(seconds=METRICS_DAY_GRACE_SECONDS)
    return day < now.date() - timedelta(days=1)


def metrics_days_since_last_calculation(finished_at: int, yesterday: date) -> List[date]:
    """The days before yesterday from the day before the last calculation finished.

    A write reopens a day only once the day is older than yesterday, so a day written while it was yesterday or
    today, with no calculation since, is found here.
    """
    day = datetime.fromtimestamp(finished_at, tz=timezone.utc).date() - timedelta(days=1)
    days = []
    while day < yesterday:
        days.append(day)
        day += timedelta(days=1)
    return days


def get_metrics_fingerprint(
    sessions: List[Dict[str, Any]], runs: List[Dict[str, Any]], yesterday: date
) -> Optional[List[Any]]:
    """The count and update times of the sessions and runs of yesterday and today. None while one of them was
    updated in the current second, which a second update in that same second would leave unchanged."""
    start_timestamp = int(datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
    current_time = int(time.time())
    fingerprint: List[Any] = [yesterday.isoformat()]
    for records in [sessions, runs]:
        updated_ats = [
            record.get("updated_at") or 0 for record in records if (record.get("created_at") or 0) >= start_timestamp
        ]
        if updated_ats and max(updated_ats) >= current_time:
            return None
        fingerprint.extend([len(updated_ats), sum(updated_ats)])
    return fingerprint


def metrics_day_to_reopen(created_at: Optional[int]) -> Optional[date]:
    """The day whose metrics a write of a run or session stored with the given created_at reopens.

    ``None`` for today and yesterday, which every calculation rebuilds anyway.
    """
    if created_at is None:
        return None
    day = datetime.fromtimestamp(created_at, tz=timezone.utc).date()
    # Without METRICS_DAY_GRACE_SECONDS: a write reopens a day as soon as its calculation can complete it
    return day if day < datetime.now(timezone.utc).date() - timedelta(days=1) else None


def reopened_user_metrics_row(
    stored_row: Optional[Dict[str, Any]], day: date, aggregation_period: str = "daily"
) -> Dict[str, Any]:
    """The everyone row of a day or a month after a write reopened it: its stored row open, with its version moved
    by one, or an empty open row when it has none."""
    if stored_row is None:
        return {**build_user_metrics_row([], aggregation_period, day, completed=False), "version": 1}
    return {**stored_row, "completed": False, "version": stored_row["version"] + 1}


def reopen_metrics_month(user_metrics_by_key: Dict[Tuple[Any, ...], Dict[str, Any]], month_start: date) -> None:
    """Reopen a month's everyone row of the given user metrics rows, so the next calculation rebuilds the month."""
    key = ("monthly", month_start, "")
    user_metrics_by_key[key] = reopened_user_metrics_row(user_metrics_by_key.get(key), month_start, "monthly")


def reopen_metrics_days_from(user_metrics_by_key: Dict[Tuple[Any, ...], Dict[str, Any]], starting_date: date) -> None:
    """Reopen every day's everyone row of the given user metrics rows from the given date on, as a write reopens a
    day, so the next calculation rebuilds them."""
    for (aggregation_period, row_date, user_id), row in list(user_metrics_by_key.items()):
        if aggregation_period == "daily" and user_id == "" and row_date >= starting_date:
            user_metrics_by_key[(aggregation_period, row_date, user_id)] = reopened_user_metrics_row(row, row_date)


def get_open_metrics_months(user_metrics_by_key: Dict[Tuple[Any, ...], Dict[str, Any]]) -> List[date]:
    """The first day of every month before the current one whose month row is still open: not completed yet, or
    reopened by a day a calculation rebuilt before it stopped."""
    current_month = datetime.now(timezone.utc).date().replace(day=1)
    return [
        row_date
        for (aggregation_period, row_date, user_id), row in user_metrics_by_key.items()
        if aggregation_period == "monthly" and user_id == "" and not row["completed"] and row_date < current_month
    ]


def get_metrics_reopen_session_ids(
    stored_sessions: List[Dict[str, Any]], session_records: List[Dict[str, Any]]
) -> Set[str]:
    """The id of each session the given rows add, move to another owner or component, or give other compaction
    metrics."""
    stored_by_id = {stored_session.get("session_id"): stored_session for stored_session in stored_sessions}
    session_ids: Set[str] = set()
    for record in session_records:
        stored_session = stored_by_id.get(record["session_id"])
        if (
            stored_session is None
            or any(
                record[column] != stored_session.get(column)
                for column in ["user_id", "agent_id", "team_id", "workflow_id"]
                if column in record
            )
            or (
                "session_data" in record
                and _session_compaction_metrics(record["session_data"])
                != _session_compaction_metrics(stored_session.get("session_data"))
            )
        ):
            session_ids.add(record["session_id"])
    return session_ids


def _session_compaction_metrics(session_data: Any) -> Optional[Dict[str, Any]]:
    """The compaction metrics of a session's session_data, which a store may keep as JSON text."""
    if isinstance(session_data, str):
        try:
            session_data = json.loads(session_data)
        except (json.JSONDecodeError, TypeError):
            return None
    return session_data.get("compaction_metrics") if isinstance(session_data, dict) else None


def build_user_metrics_row(
    rows: Sequence[Dict[str, Any]], aggregation_period: str, row_date: date, completed: bool, user_id: str = ""
) -> Dict[str, Any]:
    """Build the row of agno_aggregate_metrics that totals the given rows of agno_component_metrics.

    Args:
        rows (Sequence[Dict[str, Any]]): The rows of the period: of every user for the everyone row, of
            the user for a user's row. Empty for a period without traffic.
        aggregation_period (str): "daily" or "monthly".
        row_date (date): The day, or the first day of the month.
        completed (bool): Whether the period and its rows can be final.
        user_id (str): The user of the row. "" for the everyone row.

    Returns:
        Dict[str, Any]: The row. Its version is set when it is written.
    """
    if aggregation_period not in _METRICS_PERIODS:
        raise ValueError(f"Unknown metrics aggregation period: {aggregation_period}")
    counts = {column: 0 for column in AGGREGATE_METRICS_COUNT_COLUMNS}
    for row in rows:
        counts[f"{row['component_type']}_runs_count"] += row["runs_count"]
        counts[f"{row['component_type']}_sessions_count"] += row["sessions_count"]
    # Counted, not added, so a user of several days or components is one user of the month
    counts["users_count"] = len({row["user_id"] for row in rows if row["user_id"]})
    current_time = int(time.time())
    return {
        "aggregation_period": aggregation_period,
        "date": row_date,
        "user_id": user_id,
        # The sessions and runs of every type, kept apart in the counts of each type
        **merge_metrics_totals(
            rows, [field for field in METRICS_FIELDS if field not in ["sessions_count", "runs_count"]]
        ),
        **counts,
        # A team member, a nested team and a run started inside a tool call were started by another run
        "root_runs_count": sum(row["runs_count"] for row in rows if not row["parent_component_id"]),
        # The agno version that built the row
        "metrics_version": agno_version,
        "completed": completed,
        "created_at": current_time,
        "updated_at": current_time,
    }


def build_aggregate_metrics_rows(
    rows: Sequence[Dict[str, Any]], aggregation_period: str, row_date: date, completed: bool
) -> List[Dict[str, Any]]:
    """Build the rows of agno_aggregate_metrics that total the given rows of agno_component_metrics: the everyone row
    first, then one row per user. The runs with no user are only in the everyone row."""
    rows_by_user: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        if row["user_id"]:
            rows_by_user.setdefault(row["user_id"], []).append(row)
    return [build_aggregate_metrics_row(rows, aggregation_period, row_date, completed)] + [
        build_aggregate_metrics_row(user_rows, aggregation_period, row_date, completed, user_id=user_id)
        for user_id, user_rows in sorted(rows_by_user.items())
    ]


def _metrics_row_changed(row: Dict[str, Any], stored: Dict[str, Any]) -> bool:
    """Whether a rebuilt row differs from the stored one.

    A rebuild stamps every row anew, so the times are not compared.
    """
    return any(
        value != stored.get(column)
        for column, value in row.items()
        if column not in ["created_at", "updated_at", "version"]
    )


def component_metrics_rows_to_write(
    computed_rows: Sequence[Dict[str, Any]], stored_rows: Sequence[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str, str, str, str]]]:
    """Compare a day's rebuilt rows of agno_component_metrics with the rows stored for it.

    Returns the rows that are new or changed, in key order so no two writers lock rows in opposite
    orders, and the user, component type, component id, parent component id and root component id
    of every stored row the day no longer has.
    """

    def _row_key(row: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
        return (
            row["user_id"],
            row["component_type"],
            row["component_id"],
            row["parent_component_id"],
            row["root_component_id"],
        )

    stored_by_key = {_row_key(row): row for row in stored_rows}
    changed_rows = []
    for row in sorted(computed_rows, key=_row_key):
        stored = stored_by_key.pop(_row_key(row), None)
        if stored is None or _metrics_row_changed(row, stored):
            changed_rows.append(row)
    return changed_rows, sorted(stored_by_key)


def get_metrics_rows_by_key(
    rows: Sequence[Dict[str, Any]], key_columns: Sequence[str]
) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
    """Key the given metrics rows by the given columns, the columns a row is unique by."""
    return {tuple(row[column] for column in key_columns): row for row in rows}


def _upsert_component_metrics_rows(
    rows_by_key: Dict[Tuple[Any, ...], Dict[str, Any]], component_metrics_records: List[Dict[str, Any]]
) -> None:
    """Upsert component metrics into the given rows, by key. The created_at of a stored row is never overwritten."""
    for record in component_metrics_records:
        key = tuple(record[column] for column in COMPONENT_METRICS_KEY_COLUMNS)
        stored_row = rows_by_key.get(key)
        rows_by_key[key] = {**record, "created_at": stored_row["created_at"]} if stored_row is not None else record


def user_metrics_row_to_write(
    user_metrics_row: Dict[str, Any], stored_user_metrics_row: Optional[Dict[str, Any]], rows_changed: bool
) -> Optional[Dict[str, Any]]:
    """The aggregate metrics row to write for a period, or ``None`` when the stored one stands.

    It is written whenever a row of the period was written or deleted, so its version moves with
    every change a read of the period could see, and when it is new, changed or completed.
    """
    if (
        rows_changed
        or stored_aggregate_metrics_row is None
        or _metrics_row_changed(aggregate_metrics_row, stored_aggregate_metrics_row)
    ):
        return aggregate_metrics_row
    return None


def aggregate_metrics_rows_to_write(
    aggregate_metrics_rows: Sequence[Dict[str, Any]], stored_rows: Sequence[Dict[str, Any]], rows_changed: bool
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Compare a period's rebuilt rows of agno_aggregate_metrics, from build_aggregate_metrics_rows, with the rows
    stored for it.

    Returns the everyone row to write, or ``None`` when the stored one stands, the user rows that are new or
    changed, and the user of every stored user row the period no longer has.
    """
    stored_by_user = {row["user_id"]: row for row in stored_rows}
    everyone_row = aggregate_metrics_row_to_write(aggregate_metrics_rows[0], stored_by_user.pop("", None), rows_changed)
    changed_rows = [
        row
        for row in aggregate_metrics_rows[1:]
        if aggregate_metrics_row_to_write(row, stored_by_user.pop(row["user_id"], None), rows_changed=False) is not None
    ]
    return everyone_row, changed_rows, sorted(stored_by_user)


def user_metrics_row_to_store(
    user_metrics_row: Dict[str, Any], stored_row: Optional[Dict[str, Any]], read_version: Optional[int]
) -> Dict[str, Any]:
    """The row an upsert of a user metrics row stores.

    A new row starts at version 1, and every write of a stored one moves its version by one. A stored row is
    completed only while it still has the version read before its period's rows were rebuilt, so a reopen written
    since keeps the period open.

    Args:
        user_metrics_row (Dict[str, Any]): The row, from build_user_metrics_rows.
        stored_row (Optional[Dict[str, Any]]): The row stored under its key at the time of the write. None when there
            is none.
        read_version (Optional[int]): The version of the everyone row read before the period's rows were rebuilt.
            None for a user row, which is written with its period's everyone row, and when there was no stored row.

    Returns:
        Dict[str, Any]: The row to store.
    """
    if stored_row is None:
        return {**user_metrics_row, "version": 1}
    return {
        **user_metrics_row,
        "created_at": stored_row.get("created_at"),
        "version": stored_row["version"] + 1,
        "completed": user_metrics_row["completed"] and stored_row["version"] == read_version
        if user_metrics_row["user_id"] == ""
        else user_metrics_row["completed"],
    }


def write_user_metrics_rows(
    user_metrics_by_key: Dict[Tuple[Any, ...], Dict[str, Any]],
    user_metrics_rows: List[Dict[str, Any]],
    rows_changed: bool,
    read_version: Optional[int],
) -> None:
    """Write a period's rows of the user metrics table, from build_user_metrics_rows, into the given rows by key:
    the user rows, then the everyone row, which is completed only while it still has the version read before the
    period's rows."""
    period, period_date = user_metrics_rows[0]["aggregation_period"], user_metrics_rows[0]["date"]
    stored_rows = [row for key, row in user_metrics_by_key.items() if key[:2] == (period, period_date)]
    everyone_row, changed_rows, stale_user_ids = user_metrics_rows_to_write(
        user_metrics_rows, stored_rows, rows_changed
    )
    for user_id in stale_user_ids:
        user_metrics_by_key.pop((period, period_date, user_id))
    for user_metrics_row in changed_rows:
        key = (period, period_date, user_metrics_row["user_id"])
        user_metrics_by_key[key] = user_metrics_row_to_store(user_metrics_row, user_metrics_by_key.get(key), None)
    if everyone_row is not None:
        key = (period, period_date, "")
        user_metrics_by_key[key] = user_metrics_row_to_store(everyone_row, user_metrics_by_key.get(key), read_version)


def metrics_month_end(month_start: date) -> date:
    """The last day of the calendar month that starts on the given day."""
    return month_start.replace(day=monthrange(month_start.year, month_start.month)[1])


def metrics_full_months(starting_date: date, ending_date: date) -> List[date]:
    """The first day of every calendar month that is fully inside the given date range."""
    month_starts = []
    month_start = starting_date.replace(day=1)
    while month_start <= ending_date:
        month_end = metrics_month_end(month_start)
        if month_start >= starting_date and month_end <= ending_date:
            month_starts.append(month_start)
        if month_end == date.max:
            break
        month_start = month_end + timedelta(days=1)
    return month_starts


def get_months_to_calculate_metrics_for(days: Sequence[date]) -> List[date]:
    """Return the first day of every month that holds one of the given rebuilt days, so its month rows are rebuilt."""
    return sorted({day.replace(day=1) for day in days})


def add_metrics_month_totals(
    per_owner: Dict[Tuple[str, str, str, str, str], Dict[str, Any]], stored_rows: Sequence[Dict[str, Any]]
) -> None:
    """Add rows stored for the days of a month to the totals of each user, component, parent and root, which
    build_aggregate_metrics_month_rows builds the month rows of agno_aggregate_metrics from."""
    for row in stored_rows:
        bucket_key = (
            row["user_id"],
            row["component_type"],
            row["component_id"],
            row["parent_component_id"],
            row["root_component_id"],
        )
        bucket = per_owner.setdefault(bucket_key, empty_metrics_totals())
        add_metrics_totals(bucket, row)


def build_aggregate_metrics_month_rows(
    month_start: date, per_owner: Dict[Tuple[str, str, str, str, str], Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Build the month rows of agno_aggregate_metrics from the totals of its days.

    Args:
        month_start (date): The first day of the month.
        per_owner (Dict[Tuple[str, str, str, str, str], Dict[str, Any]]): The totals of each user,
            component, parent and root, added up by add_metrics_month_totals.

    Returns:
        List[Dict[str, Any]]: The rows, from build_aggregate_metrics_rows.
    """
    rows = [
        {
            "user_id": user_id,
            "component_type": component_type,
            "component_id": component_id,
            "parent_component_id": parent_component_id,
            "root_component_id": root_component_id,
            **bucket,
        }
        for (user_id, component_type, component_id, parent_component_id, root_component_id), bucket in sorted(
            per_owner.items()
        )
    ]
    return build_aggregate_metrics_rows(
        rows, "monthly", month_start, metrics_day_completed(metrics_month_end(month_start))
    )


def get_metrics_dates_to_calculate(
    user_metrics_by_key: Dict[Tuple[Any, ...], Dict[str, Any]],
    sessions: List[Dict[str, Any]],
    runs: List[Dict[str, Any]],
    refresh_row: Dict[str, Any],
    rebuild_from: Optional[date] = None,
) -> Tuple[List[date], Optional[List[Any]]]:
    """The days whose metrics a calculation over the given rows rebuilds, and the fingerprint of yesterday and today.

    Args:
        user_metrics_by_key (Dict[Tuple[Any, ...], Dict[str, Any]]): The user metrics rows, by key.
        sessions (List[Dict[str, Any]]): The sessions.
        runs (List[Dict[str, Any]]): The runs.
        refresh_row (Dict[str, Any]): The row of the metrics refreshes table, from _claim_metrics_refresh.
        rebuild_from (Optional[date]): The first day of a rebuild.

    Returns:
        Tuple[List[date], Optional[List[Any]]]: The days, oldest first, and the fingerprint to keep on the row of
            the metrics refreshes table.
    """
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    dates_to_process: Set[date] = set()
    fingerprint = get_metrics_fingerprint(sessions, runs, yesterday)
    first_calculation = refresh_row["finished_at"] is None
    # Yesterday and today, when their sessions or runs changed since the last calculation
    if first_calculation or fingerprint is None or fingerprint != refresh_row["fingerprint"]:
        dates_to_process.update([yesterday, today])

    # Every earlier day still open: not yet completed, or reopened by a write since
    dates_to_process.update(
        row_date
        for (aggregation_period, row_date, user_id), row in user_metrics_by_key.items()
        if aggregation_period == "daily" and user_id == "" and not row["completed"] and row_date < yesterday
    )
    # Every earlier day from the day before the last calculation finished, whose writes reopened nothing while
    # it was yesterday or today
    if not first_calculation:
        dates_to_process.update(metrics_days_since_last_calculation(refresh_row["finished_at"], yesterday))

    # Until a first calculation has finished, every day with a session or a run not yet completed; with
    # rebuild_from, every day with one from that date on. Only days with data, so one session dated long ago
    # never builds every empty day since
    if first_calculation or rebuild_from is not None:
        completed_days: Set[date] = set()
        if first_calculation:
            completed_days = {
                row_date
                for (aggregation_period, row_date, user_id), row in user_metrics_by_key.items()
                if aggregation_period == "daily" and user_id == "" and row["completed"]
            }
        for record in sessions + runs:
            if record.get("created_at") is None:
                continue
            data_date = datetime.fromtimestamp(record["created_at"], tz=timezone.utc).date()
            # A rebuild takes every day with data from its first day, completed or not
            rebuilt = rebuild_from is not None and data_date >= rebuild_from
            if data_date <= today and (rebuilt or (first_calculation and data_date not in completed_days)):
                dates_to_process.add(data_date)

    return sorted(dates_to_process), fingerprint


def calculate_date_metrics(
    rows_by_key: Dict[Tuple[Any, ...], Dict[str, Any]],
    date_to_process: date,
    sessions: List[Dict[str, Any]],
    runs: List[Dict[str, Any]],
    stored_rows: List[Dict[str, Any]],
    run_ids: Set[str],
    runs_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], bool]:
    """Rebuild the component metrics rows of one day into the given rows, and build its user metrics rows.

    Args:
        rows_by_key (Dict[Tuple[Any, ...], Dict[str, Any]]): Every component metrics row, by key.
        date_to_process (date): The day.
        sessions (List[Dict[str, Any]]): The sessions created on the day.
        runs (List[Dict[str, Any]]): The runs created on the day, legacy runs included.
        stored_rows (List[Dict[str, Any]]): The component metrics rows stored for the day.
        run_ids (Set[str]): The id of every run, legacy runs included.
        runs_by_id (Dict[str, Dict[str, Any]]): Every run, legacy runs included, by id.

    Returns:
        Tuple[List[Dict[str, Any]], bool]: The user metrics rows of the day, from build_user_metrics_rows, and whether
            any of its component rows changed.
    """
    # A nested run also stored as a run of its own, or as a legacy run of its own, is counted from that run,
    # whatever day it is on
    stored_run_ids = metrics_nested_run_ids(runs) & run_ids

    # A run started by a run of another day, such as a member run after midnight, names that run's agent, team or
    # workflow as its parent, read from every run of the calculation
    day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
    # A remote member's run after midnight is named by its team's run of the day before
    team_session_ids = metrics_remote_member_team_session_ids(runs)
    day_start = int(datetime.combine(date_to_process, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
    team_runs = [
        run
        for run in (runs_by_id.values() if team_session_ids else [])
        if run.get("session_id") in team_session_ids
        and run.get("created_at") is not None
        and day_start - 86400 <= run["created_at"] < day_start
    ]
    parent_runs = team_runs + _get_metrics_parent_runs(
        runs_by_id,
        sorted({run["parent_run_id"] for run in runs + team_runs if run.get("parent_run_id")} - day_run_ids),
    )

    records = calculate_date_component_metrics(date_to_process, sessions, runs, stored_run_ids, parent_runs)
    changed_rows, stale_keys = component_metrics_rows_to_write(records, stored_rows)
    for stale_key in stale_keys:
        rows_by_key.pop(("daily", date_to_process, *stale_key))
    _upsert_component_metrics_rows(rows_by_key, changed_rows)
    return (
        build_user_metrics_rows(records, "daily", date_to_process, metrics_day_completed(date_to_process)),
        bool(changed_rows or stale_keys),
    )


def calculate_month_metrics(
    rows_by_key: Dict[Tuple[Any, ...], Dict[str, Any]], month_start: date
) -> List[Dict[str, Any]]:
    """Build the month rows of the user metrics table from the component metrics rows of the month's days."""
    per_owner: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
    add_metrics_month_totals(
        per_owner,
        [
            row
            for row in rows_by_key.values()
            if row["aggregation_period"] == "daily" and month_start <= row["date"] <= metrics_month_end(month_start)
        ],
    )
    # Added up per owner and component over the month, so a user of several days is one user of the month
    return build_user_metrics_month_rows(month_start, per_owner)


def metrics_days_to_read(starting_date: date, ending_date: date, month_starts: Sequence[date]) -> List[date]:
    """The days of the date range that are not read from the rows of one of the given months."""
    days_diff = (ending_date - starting_date).days + 1
    days = [starting_date + timedelta(days=x) for x in range(days_diff)]
    return [day for day in days if day.replace(day=1) not in month_starts]


def metrics_day_ranges(days: Sequence[date]) -> List[Tuple[date, date]]:
    """Group days, oldest first, into the first and last day of every run of consecutive days."""
    ranges: List[Tuple[date, date]] = []
    for day in days:
        if ranges and day - ranges[-1][1] == timedelta(days=1):
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return ranges


def metrics_refresh_status(
    refresh_row: Optional[Dict[str, Any]], stale_lock_threshold: int
) -> Optional[Dict[str, Any]]:
    """The state of the most recent metrics refresh, read from the row of agno_metrics_refreshes.

    Args:
        refresh_row (Optional[Dict[str, Any]]): The row. ``None`` before the first refresh.
        stale_lock_threshold (int): The locked_at at or before which a running refresh stopped, by the database's
            clock.

    Returns:
        Optional[Dict[str, Any]]: The status ('running', 'completed' or 'failed'), when the refresh started and
            finished, and its error. ``None`` before the first refresh.
    """
    if refresh_row is None:
        return None
    status, error = refresh_row["status"], refresh_row["error"]
    if status == "running" and refresh_row["locked_at"] <= stale_lock_threshold:
        # Its lock went stale before it finished: the process that held it stopped
        status, error = "failed", METRICS_STOPPED_ERROR
    return {
        "status": status,
        "started_at": refresh_row["started_at"],
        "finished_at": refresh_row["finished_at"] if status == "completed" else None,
        "error": error if status == "failed" else None,
    }


def build_metrics_by_owner(rows: Sequence[Any], model_rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Build the rows get_metrics returns, one per user and day as agno_metrics holds them, from the rows of
    agno_component_metrics.

    Args:
        rows (Sequence[Any]): The totals of each user, day and component type: date, user_id, component_type,
            sessions_count, runs_count, every token column, cost, created_at and updated_at.
        model_rows (Sequence[Any]): The model counts of each user and day: date, user_id, model_id,
            model_provider, count and cost.

    Returns:
        List[Dict[str, Any]]: The rows, oldest first, with the keys of agno_metrics. The unowned row has user_id
            ``None``.
    """
    metrics_by_owner: Dict[Tuple[date, str], Dict[str, Any]] = {}
    for row in rows:
        user_id = row.user_id or ""
        metric = metrics_by_owner.get((row.date, user_id))
        if metric is None:
            metric = {
                "id": f"{row.date.isoformat()}_{user_id}_daily",
                "date": row.date,
                "aggregation_period": "daily",
                # Map the empty-string owner sentinel back to None for API consumers
                "user_id": user_id or None,
                # One distinct user per row, and none for the unowned one, so summed counts stay correct
                "users_count": 1 if user_id else 0,
                "agent_sessions_count": 0,
                "team_sessions_count": 0,
                "workflow_sessions_count": 0,
                "agent_runs_count": 0,
                "team_runs_count": 0,
                "workflow_runs_count": 0,
                "token_metrics": {**{field: 0 for field in METRICS_TOKEN_FIELDS}, "cost": None},
                "model_metrics": [],
                "completed": metrics_day_completed(row.date),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            metrics_by_owner[(row.date, user_id)] = metric
        metric[f"{row.component_type}_sessions_count"] += int(row.sessions_count or 0)
        metric[f"{row.component_type}_runs_count"] += int(row.runs_count or 0)
        for field in METRICS_TOKEN_FIELDS:
            metric["token_metrics"][field] += int(getattr(row, field) or 0)
        if row.cost is not None:
            metric["token_metrics"]["cost"] = (metric["token_metrics"]["cost"] or 0) + float(row.cost)
        metric["created_at"] = _merge_timestamp(metric["created_at"], row.created_at, latest=False)
        metric["updated_at"] = _merge_timestamp(metric["updated_at"], row.updated_at, latest=True)

    for row in sorted(model_rows, key=lambda x: (x.model_id, x.model_provider)):
        metric = metrics_by_owner.get((row.date, row.user_id or ""))
        if metric is not None:
            metric["model_metrics"].append(
                {
                    "model_id": row.model_id,
                    "model_provider": row.model_provider,
                    "count": int(row.count),
                    "cost": None if row.cost is None else float(row.cost),
                }
            )

    return [metrics_by_owner[key] for key in sorted(metrics_by_owner)]


def build_metrics_by_owner_from_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build the rows get_metrics returns, one per user and day as agno_metrics holds them, from stored day rows of
    agno_component_metrics read whole, for a store that cannot total them where they are stored.

    Args:
        rows (Sequence[Dict[str, Any]]): The day rows of agno_component_metrics, their date a date.

    Returns:
        List[Dict[str, Any]]: The rows, oldest first, with the keys of agno_metrics. The unowned row has user_id
            ``None``.
    """
    totals: Dict[Tuple[date, str, str], Dict[str, Any]] = {}
    models: Dict[Tuple[date, str, str, str], Dict[str, Any]] = {}
    for row in rows:
        key = (row["date"], row["user_id"] or "", row["component_type"])
        total = totals.setdefault(
            key,
            {
                "date": row["date"],
                "user_id": row["user_id"] or "",
                "component_type": row["component_type"],
                "sessions_count": 0,
                "runs_count": 0,
                **{field: 0 for field in METRICS_TOKEN_FIELDS},
                "cost": None,
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            },
        )
        total["sessions_count"] += row.get("sessions_count") or 0
        total["runs_count"] += row.get("runs_count") or 0
        for field in METRICS_TOKEN_FIELDS:
            total[field] += _metrics_token_count(row, field) or 0
        cost = _metrics_token_count(row, "cost")
        if cost is not None:
            total["cost"] = (total["cost"] or 0) + cost
        total["created_at"] = _merge_timestamp(total["created_at"], row.get("created_at"), latest=False)
        total["updated_at"] = _merge_timestamp(total["updated_at"], row.get("updated_at"), latest=True)
        for provider, provider_models in (row.get("model_metrics") or {}).items():
            for model_id, model in provider_models.items():
                model_totals = models.setdefault(
                    (row["date"], row["user_id"] or "", model_id, provider), {"count": 0, "cost": None}
                )
                model_totals["count"] += model.get("count") or 0
                if model.get("cost") is not None:
                    model_totals["cost"] = (model_totals["cost"] or 0) + model["cost"]
    return build_metrics_by_owner(
        [SimpleNamespace(**total) for total in totals.values()],
        [
            SimpleNamespace(date=day, user_id=user_id, model_id=model_id, model_provider=provider, **model)
            for (day, user_id, model_id, provider), model in models.items()
        ],
    )


def build_component_metrics_totals(
    fields: Sequence[str],
    rows_by_query: Dict[str, Sequence[Any]],
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Build the component metrics totals of each date from the rows of the totals queries.

    Args:
        fields (Sequence[str]): The columns that were totalled.
        rows_by_query (Dict[str, Sequence[Any]]): The rows of each query of build_component_metrics_totals_queries.

    Returns:
        Tuple[List[Dict[str, Any]], Optional[int]]: One dict per date, oldest first, and when the rows were
            last updated. A month totalled from its month row is one dict, dated its first day.
    """
    totals_by_date: Dict[date, Dict[str, Any]] = {}
    latest_updated_at: Optional[int] = None
    for row in rows_by_query.get("totals", []):
        day_totals: Dict[str, Any] = {"date": row.date, **empty_metrics_totals(fields)}
        for field in fields:
            # No cost when no run reported one
            if field == "cost":
                day_totals[field] = None if getattr(row, field) is None else float(getattr(row, field))
            elif field in METRICS_SUM_FIELDS:
                day_totals[field] = int(getattr(row, field) or 0)
            elif field in METRICS_MAX_COLUMNS and getattr(row, field) is not None:
                day_totals[field] = int(getattr(row, field))
        totals_by_date[row.date] = day_totals
        if row.updated_at is not None and (latest_updated_at is None or row.updated_at > latest_updated_at):
            latest_updated_at = row.updated_at

    for row in rows_by_query.get("count_maps", []):
        totals_by_date[row.date][row.field][row.key] = int(row.count)

    for row in rows_by_query.get("additional_metrics", []):
        # A whole number comes back a whole number
        value = int(row.value) if row.value == int(row.value) else float(row.value)
        totals_by_date[row.date]["additional_metrics"][row.key] = value

    for row in rows_by_query.get("model_metrics", []):
        model: Dict[str, Any] = {"count": int(row.count)}
        if row.cost is not None:
            model["cost"] = float(row.cost)
        totals_by_date[row.date]["model_metrics"].setdefault(row.model_provider, {})[row.model_id] = model

    for row in rows_by_query.get("tool_metrics", []):
        add_metrics_totals(totals_by_date[row.date], {"tool_metrics": row.tool_metrics}, ["tool_metrics"])

    return [totals_by_date[day] for day in sorted(totals_by_date)], latest_updated_at


def _metrics_token_count(row: Dict[str, Any], field: str) -> Any:
    """A token count of a stored row: its column, its key of token_details, or the total of the audio counts, or the
    cost kept in token_details, None when no run reported one."""
    if field == "cost":
        return (row["token_details"] or {}).get(field)
    if field == "audio_total_tokens":
        return sum(
            _metrics_token_count(row, audio_field) for audio_field in ["audio_input_tokens", "audio_output_tokens"]
        )
    if field in METRICS_TOKEN_DETAILS_FIELDS:
        return (row["token_details"] or {}).get(field, 0)
    return row[field]


def _metrics_row_field(row: Dict[str, Any], field: str) -> Any:
    """A field of a stored metrics row to total: its column, its key of token_details for a token count or the cost
    kept there, the total of the audio counts, the sessions of every type, or the runs no other run started."""
    if field in METRICS_TOKEN_DETAILS_FIELDS or field in ("audio_total_tokens", "cost"):
        return _metrics_token_count(row, field)
    # No costed runs when no run reported a cost
    if field == "cost_runs_count":
        return (row.get("token_details") or {}).get(field)
    # The user metrics table keeps the sessions of each type only
    if field == "sessions_count" and field not in row:
        return sum(row.get(f"{component_type}_sessions_count") or 0 for component_type in METRICS_COMPONENT_TYPES)
    # The component metrics table keeps the runs of each component: the root runs are those no other run started
    if field == "root_runs_count" and field not in row:
        return 0 if row["parent_component_id"] else row["runs_count"]
    if field == "additional_metrics":
        # Only the numbers of additional_metrics are totalled; the rest keeps no meaning across rows
        return {
            key: value
            for key, value in (row.get(field) or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    return row.get(field)


def total_metrics_rows(
    rows: Sequence[Dict[str, Any]],
    starting_date: date,
    ending_date: date,
    fields: Sequence[str],
    month_starts: Sequence[date] = (),
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Total the stored metrics rows of each date in the given date range, for a store that cannot total them where
    they are stored.

    Args:
        rows (Sequence[Dict[str, Any]]): The rows of one user of the user metrics table, or the rows with no user of
            the component metrics table, their date a date.
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        fields (Sequence[str]): The columns to total.
        month_starts (Sequence[date]): The first day of every month inside the date range to total from its month
            row instead of its days.

    Returns:
        Tuple[List[Dict[str, Any]], Optional[int]]: One dict per date, oldest first, and when the rows were last
            updated. A month totalled from its month row is one dict, dated its first day.
    """
    days = set(metrics_days_to_read(starting_date, ending_date, month_starts))
    totals_by_date: Dict[date, Dict[str, Any]] = {}
    latest_updated_at: Optional[int] = None
    for row in rows:
        if not (
            (row["aggregation_period"] == "daily" and row["date"] in days)
            or (row["aggregation_period"] == "monthly" and row["date"] in month_starts)
        ):
            continue
        day_totals = totals_by_date.setdefault(row["date"], {"date": row["date"], **empty_metrics_totals(fields)})
        add_metrics_totals(day_totals, {field: _metrics_row_field(row, field) for field in fields}, fields)
        if row.get("updated_at") is not None and (latest_updated_at is None or row["updated_at"] > latest_updated_at):
            latest_updated_at = row["updated_at"]
    return [totals_by_date[day] for day in sorted(totals_by_date)], latest_updated_at


def build_metrics_from_user_metrics(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Build the rows get_metrics returns, one per day as agno_metrics holds them, from day rows of
    agno_aggregate_metrics.

    Args:
        rows (Sequence[Any]): The everyone rows or user rows, as stored.

    Returns:
        List[Dict[str, Any]]: The rows, in the given order, with the keys of agno_metrics. The everyone row has user_id
            ``None``.
    """
    metrics: List[Dict[str, Any]] = []
    for row in rows:
        user_id = row["user_id"] or None
        metrics.append(
            {
                "id": f"{row['date'].isoformat()}_{user_id}_daily" if user_id else f"{row['date'].isoformat()}_daily",
                "date": row["date"],
                "aggregation_period": "daily",
                "user_id": user_id,
                **{column: row[column] for column in AGGREGATE_METRICS_COUNT_COLUMNS},
                "token_metrics": {field: _metrics_token_count(row, field) for field in [*METRICS_TOKEN_FIELDS, "cost"]},
                "model_metrics": list_metrics_models(row["model_metrics"]),
                "completed": metrics_day_completed(row["date"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return metrics


def owner_key(user_id: Any) -> Optional[str]:
    """Give a submitted and a stored user_id the same shape before comparing them.

    A stored row comes back as the text its column holds, so a session submitted with a
    non-string user_id would never match the row it just wrote and would be read as a write
    the owner check refused.
    """
    return None if user_id is None else str(user_id)


def get_sort_value(record: Dict[str, Any], sort_by: str) -> Any:
    """Get the sort value for a record, with fallback to created_at for updated_at.

    When sorting by 'updated_at', this function falls back to 'created_at' if
    'updated_at' is None. This ensures pre-2.0 records (which may have NULL
    updated_at values) are sorted correctly by their creation time.

    Args:
        record: The record dictionary to get the sort value from
        sort_by: The field to sort by

    Returns:
        The value to use for sorting
    """
    value = record.get(sort_by)
    # For updated_at, fall back to created_at if updated_at is None
    if value is None and sort_by == "updated_at":
        value = record.get("created_at")
    return value


def learning_search_patterns(query: str) -> List[str]:
    """Build the ILIKE patterns for a learnings text search.

    Three properties, each load-bearing:

    - The stored content mixes display names ("Sarah Chen") with slugs
      ("sarah_chen"), so runs of spaces and underscores in the query become the
      single-char LIKE wildcard ``_`` - one pattern crosses both forms.
    - ``%`` and ``\\`` in the query are escaped (callers pass the pattern with
      ``escape="\\\\"``), so a model-authored query containing ``%`` cannot
      collapse search into match-everything-by-recency.
    - SQLite stores JSON with ``ensure_ascii`` escapes (``café`` is stored as
      ``caf\\u00e9``), so a non-ASCII query also gets its JSON-escaped variant;
      on Postgres, where ``::text`` renders real characters, that extra pattern
      simply never matches.

    A query with no content beyond wildcards and whitespace yields no patterns.

    Args:
        query: The text to search for.

    Returns:
        Deduplicated '%...%' patterns to OR together with ILIKE (escape '\\').
    """
    import re

    stripped = query.strip()
    if not re.sub(r"[%_\s]+", "", stripped):
        return []

    variants = [stripped]
    # SQLite stores JSON with ensure_ascii escapes, and LIKE folds ASCII only,
    # so an escape sequence never case-matches: a stored "Ος" is unreachable
    # from "ΟΣ", "ος" or "οσ". No set of pre-cased whole-string variants covers
    # the mixed forms, so the escape carries a wildcard per character instead -
    # \\uXXXX is six characters wide - and the caller's value-scoped Python
    # check (which casefolds) rejects whatever that lets through. Loose
    # prefilter, precise verification, which is what this pair is for.
    #
    # The wildcards are carried as a sentinel until after the separator
    # collapse below, which would otherwise fold a run of them into one.
    wildcard = "\x00"
    json_form = json.dumps(stripped, ensure_ascii=True)[1:-1]
    if json_form != stripped:
        variants.append(re.sub(r"\\u[0-9a-fA-F]{4}", wildcard * 6, json_form))

    patterns: List[str] = []
    for variant in variants:
        escaped = variant.replace("\\", "\\\\").replace("%", "\\%")
        # Runs of separators collapse to the single-char wildcard, so one
        # pattern crosses the display-name/slug boundary in both directions
        # ("sarah chen", "sarah_chen", "sarah__chen"). The hyphen is one of
        # them: without it "multi-tenant" could never reach a stored "multi
        # tenant", and the client-side verifier - which does fold hyphens -
        # was already accepting what this pattern refused to fetch.
        crossed = re.sub(r"[\s_\-]+", "_", escaped).replace(wildcard, "_")
        pattern = f"%{crossed}%"
        if pattern not in patterns:
            patterns.append(pattern)
    return patterns


class CustomJSONEncoder(json.JSONEncoder):
    """Custom encoder to handle non JSON serializable types."""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif isinstance(obj, Message):
            return obj.to_dict()
        elif isinstance(obj, (RunMetrics, SessionMetrics, ModelMetrics)):
            return obj.to_dict()
        elif isinstance(obj, type):
            return str(obj)

        return super().default(obj)


def json_serializer(obj: Any) -> str:
    """Custom JSON serializer for SQLAlchemy engine.

    This function is used as the json_serializer parameter when creating
    SQLAlchemy engines for PostgreSQL. It handles non-JSON-serializable
    types like datetime, date, UUID, etc.

    Args:
        obj: The object to serialize to JSON.

    Returns:
        JSON string representation of the object.
    """
    return json.dumps(obj, cls=CustomJSONEncoder)


def deserialize_session_json_fields(session: dict) -> dict:
    """Deserialize JSON fields in the given Session dictionary.

    Args:
        session (dict): The dictionary to deserialize.

    Returns:
        dict: The dictionary with JSON string fields deserialized to objects.
    """
    from agno.utils.log import log_warning

    if session.get("agent_data") is not None and isinstance(session["agent_data"], str):
        try:
            session["agent_data"] = json.loads(session["agent_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse agent_data as JSON, keeping as string: {str(e)}")

    if session.get("team_data") is not None and isinstance(session["team_data"], str):
        try:
            session["team_data"] = json.loads(session["team_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse team_data as JSON, keeping as string: {str(e)}")

    if session.get("workflow_data") is not None and isinstance(session["workflow_data"], str):
        try:
            session["workflow_data"] = json.loads(session["workflow_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse workflow_data as JSON, keeping as string: {str(e)}")

    if session.get("metadata") is not None and isinstance(session["metadata"], str):
        try:
            session["metadata"] = json.loads(session["metadata"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse metadata as JSON, keeping as string: {str(e)}")

    if session.get("chat_history") is not None and isinstance(session["chat_history"], str):
        try:
            session["chat_history"] = json.loads(session["chat_history"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse chat_history as JSON, keeping as string: {str(e)}")

    if session.get("summary") is not None and isinstance(session["summary"], str):
        try:
            session["summary"] = json.loads(session["summary"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse summary as JSON, keeping as string: {str(e)}")

    if session.get("session_data") is not None and isinstance(session["session_data"], str):
        try:
            session["session_data"] = json.loads(session["session_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse session_data as JSON, keeping as string: {str(e)}")

    # Handle runs field with session type checking
    if session.get("runs") is not None and isinstance(session["runs"], str):
        try:
            session["runs"] = json.loads(session["runs"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse runs as JSON, keeping as string: {str(e)}")

    return session


def db_from_dict(db_data: Dict[str, Any]) -> Optional[Union["BaseDb", "AsyncBaseDb"]]:
    """
    Create a database instance from a dictionary.

    Args:
        db_data: Dictionary containing database configuration

    Returns:
        Database instance or None if creation fails
    """
    db_type = db_data.get("type")
    if db_type == "postgres":
        try:
            from agno.db.postgres import PostgresDb

            return PostgresDb.from_dict(db_data)
        except Exception as e:
            log_error(f"Error reconstructing PostgresDb from dictionary: {str(e)}")
            return None
    elif db_type == "sqlite":
        try:
            from agno.db.sqlite import SqliteDb

            return SqliteDb.from_dict(db_data)
        except Exception as e:
            log_error(f"Error reconstructing SqliteDb from dictionary: {str(e)}")
            return None
    elif db_type == "async_postgres":
        try:
            from agno.db.postgres import AsyncPostgresDb

            return AsyncPostgresDb.from_dict(db_data)
        except Exception as e:
            log_error(f"Error reconstructing AsyncPostgresDb from dictionary: {str(e)}")
            return None
    elif db_type == "async_sqlite":
        try:
            from agno.db.sqlite import AsyncSqliteDb

            return AsyncSqliteDb.from_dict(db_data)
        except Exception as e:
            log_error(f"Error reconstructing AsyncSqliteDb from dictionary: {str(e)}")
            return None
    elif db_type == "clickhouse":
        try:
            from agno.db.clickhouse import ClickhouseDb

            return ClickhouseDb.from_dict(db_data)
        except Exception as e:
            log_error(f"Error reconstructing ClickhouseDb from dictionary: {str(e)}")
            return None
    else:
        log_warning(f"Unknown database type: {db_type}")
        return None


def _clone_db_with_table_overrides(
    source_db: "BaseDb",
    db_data: Dict[str, Any],
) -> Optional["BaseDb"]:
    """Create a new ``BaseDb`` that shares ``source_db``'s engine but
    applies the table-name overrides from ``db_data``.

    Sharing the underlying SQLAlchemy engine is critical: otherwise every
    component load would spin up its own connection pool and blow past
    backend connection limits. This helper is used when the stored
    config references a known db (same id) but customizes table names.

    Connection metadata (``db_url`` / ``db_file`` / ``db_schema``) is
    carried over from ``source_db`` so the clone's ``to_dict`` still
    round-trips to a usable config if it is re-saved and later loaded
    without a registry.

    Returns ``None`` if the source db type is not recognized, so the
    caller can decide how to fall back.
    """
    overrides: Dict[str, Any] = {key: db_data[key] for key in DB_TABLE_NAME_KEYS if key in db_data}

    def _accepted_by(cls: Any) -> Dict[str, Any]:
        """Only pass table overrides the adapter's constructor accepts: not
        every adapter supports every table (e.g. job_table is queue-capable
        adapters only), and one unexpected kwarg would TypeError the clone
        and silently drop ALL overrides via the fallback."""
        import inspect as _inspect

        try:
            params = _inspect.signature(cls.__init__).parameters
        except (TypeError, ValueError):
            return overrides
        if any(p.kind == _inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return overrides
        return {k: v for k, v in overrides.items() if k in params}

    try:
        from agno.db.postgres import PostgresDb

        if isinstance(source_db, PostgresDb):
            overrides_filtered = _accepted_by(PostgresDb)
            return PostgresDb(
                db_url=source_db.db_url,
                db_engine=source_db.db_engine,
                db_schema=source_db.db_schema,
                id=source_db.id,
                create_schema=source_db.create_schema,
                **overrides_filtered,
            )
    except Exception as e:
        log_error(f"Error cloning PostgresDb with table overrides: {str(e)}")
        return None

    try:
        from agno.db.sqlite import SqliteDb

        if isinstance(source_db, SqliteDb):
            overrides_filtered = _accepted_by(SqliteDb)
            return SqliteDb(
                db_file=source_db.db_file,
                db_url=source_db.db_url,
                db_engine=source_db.db_engine,
                id=source_db.id,
                **overrides_filtered,
            )
    except Exception as e:
        log_error(f"Error cloning SqliteDb with table overrides: {str(e)}")
        return None

    return None


def resolve_db_from_config(
    db_data: Dict[str, Any],
    registry: Optional["Registry"] = None,
) -> Optional[Union["BaseDb", "AsyncBaseDb"]]:
    """Resolve a serialized db config to a synchronous or asynchronous database.

    Prefers a registered db instance (for connection reuse) when the
    serialized config does not override any table names. If it does, a
    clone of the registered instance is returned that **shares the same
    engine/connection pool** but carries the table-name overrides, so
    component reloads don't proliferate engines.

    Only when there is no registry match (or the registered db type is
    unknown to the cloner) do we fall through to :func:`db_from_dict`,
    which builds a fresh instance with its own engine.

    Args:
        db_data: Serialized db config dict (as produced by
            ``BaseDb.to_dict``). Expected to carry a ``type`` plus any
            table-name overrides.
        registry: Optional ``Registry`` to look up an already-constructed
            db instance by id.

    Returns:
        A database instance, or ``None`` if reconstruction fails.
    """
    db_id = db_data.get("id")
    if registry is not None and db_id:
        registry_db = registry.get_db(db_id)
        if registry_db is not None:
            registry_dict = registry_db.to_dict()
            # to_dict leaves out metrics_table when it is the default, but a saved config can still carry the default
            registry_dict.setdefault("metrics_table", registry_db.metrics_table_name)
            has_table_overrides = any(
                key in db_data and db_data[key] != registry_dict.get(key) for key in DB_TABLE_NAME_KEYS
            )
            if not has_table_overrides:
                return registry_db
            # Stored config customizes table names. Clone the registered
            # db so we reuse its engine/pool and only swap table names.
            clone = _clone_db_with_table_overrides(registry_db, db_data)
            if clone is not None:
                return clone
            # The registered db type isn't one the cloner knows how to
            # rebuild (e.g. JsonDb, RedisDb, FirestoreDb, DynamoDb, ...).
            # Fall back to the registered instance rather than building
            # a fresh one via db_from_dict, which only handles postgres
            # and sqlite and would return None for these backends. This
            # means table overrides are silently ignored for unsupported
            # types, but the component still gets a working db — same as
            # the pre-override behavior for those backends.
            log_warning(
                f"Cannot apply table-name overrides to db of type {type(registry_db).__name__}; "
                "reusing the registered instance with its configured table names."
            )
            return registry_db

    return db_from_dict(db_data)
