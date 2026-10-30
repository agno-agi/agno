"""Logic shared across different database implementations"""

import json
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple, Union
from uuid import UUID

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
        "os_metrics_table",
        "os_metrics_totals_table",
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


def metrics_starting_date_from_records(records: Sequence[Dict[str, Any]]) -> Optional[date]:
    """The first day a metrics recalculation still has to rebuild, or ``None`` if there are no records.

    A day holding a completed record was rebuilt after it ended, so an incomplete record
    sharing that day belongs to an owner whose sessions have since gone: no recalculation
    can rebuild it, and resuming there would restart at that day for good. Only the days
    after the last completed one are still owing, and the earliest is where the work resumes.
    The day never runs past today, whatever date a record carries.
    """
    latest_completed: Optional[date] = None
    incomplete_dates: List[date] = []

    for record in records:
        day = _metric_day(record)
        if day is None:
            continue
        if record.get("completed"):
            if latest_completed is None or day > latest_completed:
                latest_completed = day
        else:
            incomplete_dates.append(day)

    still_incomplete = [day for day in incomplete_dates if latest_completed is None or day > latest_completed]
    return metrics_starting_date_from_days(latest_completed, min(still_incomplete) if still_incomplete else None)


def metrics_starting_date_from_days(
    latest_completed: Optional[date], earliest_incomplete: Optional[date]
) -> Optional[date]:
    """The day a metrics recalculation resumes at, given the two days its backend queried for.

    The rule: resume at the earliest incomplete day after the latest completed one, otherwise at
    the day after that completed one, and nowhere at all (``None``) when neither day exists.
    Backends holding every record in memory find the two days by scanning them; the rest ask their
    own database, since a MAX and a MIN are what it is for. Only the decision is shared, so the day
    after a completed one is not arrived at nine ways.

    The day is capped at today: a record dated in the future puts the resume point past the last
    day there is to rebuild, so the caller's list of days to process comes back empty and every
    recalculation from then on does nothing at all.
    """
    if earliest_incomplete is not None:
        resume_at = earliest_incomplete
    elif latest_completed is not None:
        resume_at = latest_completed + timedelta(days=1)
    else:
        return None
    return min(resume_at, datetime.now(timezone.utc).date())


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
    """Merge extra model_metrics into target in place, summing counts per model."""
    index: Dict[Any, dict] = {}
    for m in [*target, *extra]:
        key = (m.get("model_id"), m.get("model_provider"))
        entry = index.get(key)
        if entry is None:
            index[key] = dict(m)
        else:
            entry["count"] = (entry.get("count") or 0) + (m.get("count") or 0)
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


# The periods a row of either OS metrics table covers. A month row is dated the first day of
# its month.
OS_METRICS_PERIODS = ("daily", "monthly")

# What a row of agno_os_metrics is counted under, by the type of the session or run.
OS_METRICS_COMPONENT_TYPES = ("agent", "team", "workflow")

# The columns a row of agno_os_metrics is unique by, and a row of agno_os_metrics_totals.
OS_METRICS_KEY_COLUMNS = (
    "aggregation_period",
    "date",
    "user_id",
    "component_type",
    "component_id",
    "parent_component_id",
)
OS_METRICS_TOTALS_KEY_COLUMNS = ("aggregation_period", "date")

# The token counts kept in columns of their own. The rarer ones are kept in
# additional_token_metrics.
_OS_METRICS_TOKEN_COLUMNS = ("input_tokens", "output_tokens", "total_tokens")
_OS_METRICS_ADDITIONAL_TOKEN_FIELDS = (
    "audio_total_tokens",
    "audio_input_tokens",
    "audio_output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)

# Every token count a model call reports that OS metrics keep, the same ones agno_metrics keeps.
OS_METRICS_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "audio_total_tokens",
    "audio_input_tokens",
    "audio_output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)

# The upper bounds, in milliseconds, of the buckets each timing is counted into. A change to the
# bounds is a new OS_METRICS_BUCKETS_VERSION, so stored rows can be told apart from new ones.
_OS_METRICS_BUCKET_BOUNDS_MS = (
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
OS_METRICS_BUCKETS_VERSION = 1

# Each timing a row keeps: how many were counted, their total and their maximum in milliseconds,
# and their buckets.
_OS_METRICS_TIMINGS = {
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
OS_METRICS_SUM_COLUMNS = (
    "sessions_count",
    "runs_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "duration_runs_count",
    "time_to_first_token_runs_count",
    "model_calls_count",
    "total_duration_ms",
    "total_time_to_first_token_ms",
    "total_model_call_ms",
)
OS_METRICS_MAX_COLUMNS = ("max_duration_ms", "max_time_to_first_token_ms", "max_model_call_ms")
OS_METRICS_COUNT_MAP_COLUMNS = (
    "status_metrics",
    "additional_token_metrics",
    "duration_buckets",
    "time_to_first_token_buckets",
    "model_call_buckets",
)

# What get_os_metrics can total, and totals when the caller names none.
OS_METRICS_FIELDS = (
    "sessions_count",
    "runs_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "duration_runs_count",
    "time_to_first_token_runs_count",
    "model_calls_count",
    "total_duration_ms",
    "total_time_to_first_token_ms",
    "total_model_call_ms",
    "max_duration_ms",
    "max_time_to_first_token_ms",
    "max_model_call_ms",
    "status_metrics",
    "additional_token_metrics",
    "duration_buckets",
    "time_to_first_token_buckets",
    "model_call_buckets",
    "model_metrics",
    "additional_metrics",
)


def resolve_os_metrics_fields(fields: Optional[Sequence[str]]) -> List[str]:
    """The columns a get_os_metrics call totals, rejecting any the table does not have."""
    if fields is None:
        return list(OS_METRICS_FIELDS)
    unknown = [field for field in fields if field not in OS_METRICS_FIELDS]
    if unknown:
        raise ValueError(f"Unknown OS metrics fields: {unknown}")
    return list(fields)


def empty_os_metrics_totals(fields: Sequence[str] = OS_METRICS_FIELDS) -> Dict[str, Any]:
    """The totals of no row: zero counts, no maximum, empty maps and no models."""
    totals: Dict[str, Any] = {
        "sessions_count": 0,
        "runs_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "duration_runs_count": 0,
        "time_to_first_token_runs_count": 0,
        "model_calls_count": 0,
        "total_duration_ms": 0,
        "total_time_to_first_token_ms": 0,
        "total_model_call_ms": 0,
        "max_duration_ms": None,
        "max_time_to_first_token_ms": None,
        "max_model_call_ms": None,
        "status_metrics": {},
        "additional_token_metrics": {},
        "duration_buckets": {},
        "time_to_first_token_buckets": {},
        "model_call_buckets": {},
        "model_metrics": [],
        "additional_metrics": {},
    }
    return {field: totals[field] for field in fields}


def add_os_metrics_totals(
    target: Dict[str, Any], extra: Dict[str, Any], fields: Sequence[str] = OS_METRICS_FIELDS
) -> None:
    """Add the totals of extra to target in place.

    Counts and maps are summed, maximums keep the larger value, and additional_metrics is merged
    the way RunMetrics.additional_metrics is.
    """
    for field in fields:
        value = extra.get(field)
        if field in OS_METRICS_SUM_COLUMNS:
            target[field] = (target.get(field) or 0) + (value or 0)
        elif field in OS_METRICS_MAX_COLUMNS:
            if value is not None and (target.get(field) is None or value > target[field]):
                target[field] = value
        elif field == "model_metrics":
            model_metrics = list(target.get(field) or [])
            _merge_model_metrics(model_metrics, value or [])
            # Sorted so the same models total to the same list
            target[field] = sorted(model_metrics, key=lambda model: (model["model_id"], model["model_provider"]))
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


def merge_os_metrics_totals(totals: Sequence[Dict[str, Any]], fields: Sequence[str]) -> Dict[str, Any]:
    """Merge the OS metrics totals of several dates or databases into one set of totals."""
    merged = empty_os_metrics_totals(fields)
    for extra in totals:
        add_os_metrics_totals(merged, extra, fields)
    return merged


def _os_metrics_component(record: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """The component_type and component_id a session or run is counted under, by its type.

    ``None`` for a type that is no agent, team or workflow, which no row can be kept under.
    """
    component_type = record.get("session_type") or record.get("run_type")
    if component_type not in OS_METRICS_COMPONENT_TYPES:
        record_id = record.get("run_id") or record.get("session_id")
        log_warning(f"Skipping OS metrics of {record_id}: type {component_type!r} is not an agent, team or workflow")
        return None
    return component_type, record.get(f"{component_type}_id") or ""


def _os_metrics_parent_component_id(run: Dict[str, Any], components: Dict[str, Tuple[str, str]]) -> str:
    """The id of the agent, team or workflow whose run started the given run.

    Empty for a run no run started.
    """
    _, component_id = components.get(run.get("parent_run_id") or "", ("", ""))
    return component_id


def _os_metrics_nested_runs(run_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The runs nested inside a stored run: its workflow steps' runs, its team members' runs and its workflow
    agent's run."""
    workflow_agent_run = run_data.get("workflow_agent_run")
    return (
        (run_data.get("step_executor_runs") or [])
        + (run_data.get("member_responses") or [])
        + ([workflow_agent_run] if workflow_agent_run else [])
    )


def _add_os_metrics_nested_run_ids(run_data: Dict[str, Any], nested_run_ids: Set[str]) -> None:
    """Add the ids of every run nested inside run_data, at any depth, to nested_run_ids."""
    for nested_run in _os_metrics_nested_runs(run_data):
        if nested_run.get("run_id"):
            nested_run_ids.add(nested_run["run_id"])
        _add_os_metrics_nested_run_ids(nested_run, nested_run_ids)


def os_metrics_nested_run_ids(runs: Sequence[Dict[str, Any]]) -> Set[str]:
    """The ids of every run nested inside a day's stored runs, at any depth.

    A nested run ending after midnight is stored on the next day, so the rollup asks the runs table
    which of these ids exist before it walks the nested runs.
    """
    nested_run_ids: Set[str] = set()
    for run in runs:
        _add_os_metrics_nested_run_ids(run.get("run_data") or {}, nested_run_ids)
    return nested_run_ids


def get_os_metrics_legacy_runs(sessions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The runs kept in the legacy runs field of the given sessions, as runs table records.

    A legacy run is dated by its own created_at, else by its session's, and typed by its ids, as the v3.0.0
    migration types it. The caller drops the ones the runs table also holds, as merge_runs_table_with_legacy_blob
    does.
    """
    legacy_runs = []
    for session in sessions:
        runs = session.get("runs")
        if isinstance(runs, str):
            try:
                runs = json.loads(runs)
            except (json.JSONDecodeError, TypeError):
                log_warning("Could not parse legacy runs blob during OS metrics calculation; ignoring it")
                runs = None
        if not isinstance(runs, list):
            continue
        for run in runs:
            # The migration skips what is no run
            if not isinstance(run, dict) or run.get("run_id") is None:
                continue
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


def _os_metrics_model_calls(run_data: Dict[str, Any], seen_run_ids: Set[str]) -> List[Dict[str, Any]]:
    """Every model call a stored run holds, skipping nested runs already counted."""
    calls = [run_data] if run_data.get("model") else []
    for nested_run in _os_metrics_nested_runs(run_data):
        run_id = nested_run.get("run_id")
        if run_id in seen_run_ids:
            continue
        if run_id:
            seen_run_ids.add(run_id)
        calls.extend(_os_metrics_model_calls(nested_run, seen_run_ids))
    return calls


def _os_metrics_call_durations(call: Dict[str, Any]) -> List[float]:
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


def _os_metrics_bucket(milliseconds: int) -> str:
    """The bucket a timing is counted into."""
    for bound in _OS_METRICS_BUCKET_BOUNDS_MS:
        if milliseconds <= bound:
            return f"le_{bound}"
    return f"gt_{_OS_METRICS_BUCKET_BOUNDS_MS[-1]}"


def _add_os_metrics_timing(totals: Dict[str, Any], timing: str, seconds: Optional[float]) -> None:
    """Add one timing to a row: a count, a total and a maximum in milliseconds, and its bucket."""
    if seconds is None:
        return
    count_column, total_column, max_column, buckets_column = _OS_METRICS_TIMINGS[timing]
    milliseconds = int(round(seconds * 1000))
    totals[count_column] += 1
    totals[total_column] += milliseconds
    totals[max_column] = milliseconds if totals[max_column] is None else max(totals[max_column], milliseconds)
    bucket = _os_metrics_bucket(milliseconds)
    totals[buckets_column][bucket] = totals[buckets_column].get(bucket, 0) + 1


def calculate_date_os_metrics(
    date_to_process: date,
    sessions: List[Dict[str, Any]],
    runs: List[Dict[str, Any]],
    stored_run_ids: Set[str],
    parent_runs: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Calculate OS metrics for the given single date, one row per user and agent, team or workflow.

    The runs another run of the date started are counted apart, under the id of what started
    them. The tokens of a run nested inside another, and not stored as a run of its own, are
    counted on the row of the run it is nested inside.

    Args:
        date_to_process (date): The date to calculate OS metrics for.
        sessions (List[Dict[str, Any]]): The sessions created on that date.
        runs (List[Dict[str, Any]]): The runs created on that date, as stored.
        stored_run_ids (Set[str]): The ids of the nested runs of that date that are stored as
            runs of their own, on any date. Those are counted where they are stored.
        parent_runs (Sequence[Dict[str, Any]]): The runs of another date that started runs of
            that date, such as a team run started before midnight. Only their ids are read.

    Returns:
        List[Dict[str, Any]]: The calculated rows of agno_os_metrics, one per user, agent, team
            or workflow and parent.
    """
    per_owner: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    for session in sessions:
        component = _os_metrics_component(session)
        if component is None:
            continue
        bucket_key = (session.get("user_id") or "", *component, "")
        bucket = per_owner.setdefault(bucket_key, empty_os_metrics_totals())
        bucket["sessions_count"] += 1

    seen_run_ids = {run["run_id"] for run in runs if run.get("run_id")} | stored_run_ids
    components = {
        run["run_id"]: component
        for run in list(runs) + list(parent_runs)
        if run.get("run_id") and (component := _os_metrics_component(run)) is not None
    }
    for run in runs:
        # A run copied into a forked session repeats a run counted in the session it was made in
        if (run.get("run_data") or {}).get("forked_from_session_id"):
            continue
        component = components.get(run["run_id"]) if run.get("run_id") else _os_metrics_component(run)
        if component is None:
            continue
        bucket_key = (run.get("user_id") or "", *component, _os_metrics_parent_component_id(run, components))
        bucket = per_owner.setdefault(bucket_key, empty_os_metrics_totals())
        status = run.get("status")
        run_data = run.get("run_data") or {}
        run_metrics = run_data.get("metrics") or {}

        # A new run replaced a regenerated run, so it is not counted, but its model calls still count
        if status != RunStatus.regenerated.value:
            bucket["runs_count"] += 1
            if status:
                bucket["status_metrics"][status] = bucket["status_metrics"].get(status, 0) + 1
        if status == RunStatus.completed.value:
            _add_os_metrics_timing(bucket, "duration", run_metrics.get("duration"))
            _add_os_metrics_timing(bucket, "time_to_first_token", run_metrics.get("time_to_first_token"))

        for call in _os_metrics_model_calls(run_data, seen_run_ids):
            call_metrics = call.get("metrics") or {}
            for field in _OS_METRICS_TOKEN_COLUMNS:
                bucket[field] += call_metrics.get(field) or 0
            for field in _OS_METRICS_ADDITIONAL_TOKEN_FIELDS:
                if value := call_metrics.get(field):
                    bucket["additional_token_metrics"][field] = bucket["additional_token_metrics"].get(field, 0) + value
            for seconds in _os_metrics_call_durations(call):
                _add_os_metrics_timing(bucket, "model_call", seconds)

            # A model that failed before answering reports no details, so it served nothing
            if call_metrics.get("details"):
                model = {"model_id": call["model"], "model_provider": call.get("model_provider") or "", "count": 1}
                _merge_model_metrics(bucket["model_metrics"], [model])

    current_time = int(time.time())

    records: List[dict] = []
    for (user_id, component_type, component_id, parent_component_id), bucket in sorted(per_owner.items()):
        # Sorted so an unchanged day rebuilds to the same list
        model_metrics = sorted(bucket["model_metrics"], key=lambda model: (model["model_id"], model["model_provider"]))

        records.append(
            {
                "aggregation_period": "daily",
                "date": date_to_process,
                "user_id": user_id,
                "component_type": component_type,
                "component_id": component_id,
                "parent_component_id": parent_component_id,
                "sessions_count": bucket["sessions_count"],
                "runs_count": bucket["runs_count"],
                "input_tokens": bucket["input_tokens"],
                "output_tokens": bucket["output_tokens"],
                "total_tokens": bucket["total_tokens"],
                "duration_runs_count": bucket["duration_runs_count"],
                "time_to_first_token_runs_count": bucket["time_to_first_token_runs_count"],
                "model_calls_count": bucket["model_calls_count"],
                "total_duration_ms": bucket["total_duration_ms"],
                "total_time_to_first_token_ms": bucket["total_time_to_first_token_ms"],
                "total_model_call_ms": bucket["total_model_call_ms"],
                "max_duration_ms": bucket["max_duration_ms"],
                "max_time_to_first_token_ms": bucket["max_time_to_first_token_ms"],
                "max_model_call_ms": bucket["max_model_call_ms"],
                "status_metrics": bucket["status_metrics"],
                "additional_token_metrics": bucket["additional_token_metrics"],
                "duration_buckets": bucket["duration_buckets"],
                "time_to_first_token_buckets": bucket["time_to_first_token_buckets"],
                "model_call_buckets": bucket["model_call_buckets"],
                "model_metrics": model_metrics,
                "additional_metrics": bucket["additional_metrics"],
                "buckets_version": OS_METRICS_BUCKETS_VERSION,
                "created_at": current_time,
                "updated_at": current_time,
            }
        )

    return records


def os_metrics_day_completed(day: date) -> bool:
    """Whether a day's OS metrics are final.

    A run can be written again after its day ended, so a day is completed one day later.
    """
    return day < datetime.now(timezone.utc).date() - timedelta(days=1)


def build_os_metrics_totals_row(
    rows: Sequence[Dict[str, Any]], aggregation_period: str, row_date: date, completed: bool
) -> Dict[str, Any]:
    """Build the row of agno_os_metrics_totals that totals the given rows of agno_os_metrics.

    Args:
        rows (Sequence[Dict[str, Any]]): The rows of the period, of every user. Empty for a period
            without traffic.
        aggregation_period (str): "daily" or "monthly".
        row_date (date): The day, or the first day of the month.
        completed (bool): Whether the period and its rows are final.

    Returns:
        Dict[str, Any]: The row. Its version is set when it is written.
    """
    if aggregation_period not in OS_METRICS_PERIODS:
        raise ValueError(f"Unknown OS metrics aggregation period: {aggregation_period}")
    totals = merge_os_metrics_totals(rows, OS_METRICS_FIELDS)
    current_time = int(time.time())
    return {
        "aggregation_period": aggregation_period,
        "date": row_date,
        "sessions_count": totals["sessions_count"],
        "runs_count": totals["runs_count"],
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "total_tokens": totals["total_tokens"],
        "duration_runs_count": totals["duration_runs_count"],
        "time_to_first_token_runs_count": totals["time_to_first_token_runs_count"],
        "model_calls_count": totals["model_calls_count"],
        "total_duration_ms": totals["total_duration_ms"],
        "total_time_to_first_token_ms": totals["total_time_to_first_token_ms"],
        "total_model_call_ms": totals["total_model_call_ms"],
        "max_duration_ms": totals["max_duration_ms"],
        "max_time_to_first_token_ms": totals["max_time_to_first_token_ms"],
        "max_model_call_ms": totals["max_model_call_ms"],
        "status_metrics": totals["status_metrics"],
        "additional_token_metrics": totals["additional_token_metrics"],
        "duration_buckets": totals["duration_buckets"],
        "time_to_first_token_buckets": totals["time_to_first_token_buckets"],
        "model_call_buckets": totals["model_call_buckets"],
        "model_metrics": totals["model_metrics"],
        "additional_metrics": totals["additional_metrics"],
        "buckets_version": OS_METRICS_BUCKETS_VERSION,
        "completed": completed,
        "created_at": current_time,
        "updated_at": current_time,
    }


def _os_metrics_row_changed(row: Dict[str, Any], stored: Dict[str, Any]) -> bool:
    """Whether a rebuilt row differs from the stored one.

    A rebuild stamps every row anew, so the times are not compared.
    """
    return any(
        value != stored.get(column)
        for column, value in row.items()
        if column not in ["created_at", "updated_at", "version"]
    )


def os_metrics_rows_to_write(
    computed_rows: Sequence[Dict[str, Any]], stored_rows: Sequence[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str, str, str]]]:
    """Compare a day's rebuilt rows of agno_os_metrics with the rows stored for it.

    Returns the rows that are new or changed, in key order so no two writers lock rows in opposite
    orders, and the user, component type, component id and parent component id of every stored row
    the day no longer has.
    """

    def _row_key(row: Dict[str, Any]) -> Tuple[str, str, str, str]:
        return row["user_id"], row["component_type"], row["component_id"], row["parent_component_id"]

    stored_by_key = {_row_key(row): row for row in stored_rows}
    changed_rows = []
    for row in sorted(computed_rows, key=_row_key):
        stored = stored_by_key.pop(_row_key(row), None)
        if stored is None or _os_metrics_row_changed(row, stored):
            changed_rows.append(row)
    return changed_rows, sorted(stored_by_key)


def os_metrics_totals_row_to_write(
    totals_row: Dict[str, Any], stored_totals_row: Optional[Dict[str, Any]], rows_changed: bool
) -> Optional[Dict[str, Any]]:
    """The totals row to write for a period, or ``None`` when the stored one stands.

    It is written whenever a row of the period was written or deleted, so its version moves with
    every change a read of the period could see, and when it is new, changed or completed.
    """
    if rows_changed or stored_totals_row is None or _os_metrics_row_changed(totals_row, stored_totals_row):
        return totals_row
    return None


def os_metrics_month_end(month_start: date) -> date:
    """The last day of the calendar month that starts on the given day."""
    return month_start.replace(day=monthrange(month_start.year, month_start.month)[1])


def os_metrics_full_months(starting_date: date, ending_date: date) -> List[date]:
    """The first day of every calendar month that is fully inside the given date range."""
    month_starts = []
    month_start = starting_date.replace(day=1)
    while month_start <= ending_date:
        month_end = os_metrics_month_end(month_start)
        if month_start >= starting_date and month_end <= ending_date:
            month_starts.append(month_start)
        if month_end == date.max:
            break
        month_start = month_end + timedelta(days=1)
    return month_starts


def get_months_to_calculate_os_metrics_for(
    day_starts: Sequence[date], calculated_months: Sequence[date], latest_completed: Optional[date]
) -> List[date]:
    """Return the list of months to calculate month rows for.

    Days are completed in order, so a month is completed once its last day is at or before the
    latest completed day. Every completed month with days and no month rows is returned, whenever
    its days were rebuilt, so a month one rebuild could not calculate is calculated by a later one.

    Args:
        day_starts (Sequence[date]): The days that have a totals row.
        calculated_months (Sequence[date]): The first day of every month that has a totals row.
        latest_completed (Optional[date]): The latest completed day. ``None`` when no day is
            completed.

    Returns:
        List[date]: The first day of every month to calculate month rows for.
    """
    if latest_completed is None:
        return []
    month_starts = {day.replace(day=1) for day in day_starts} - set(calculated_months)
    return sorted(month_start for month_start in month_starts if os_metrics_month_end(month_start) <= latest_completed)


def add_month_os_metrics(
    per_owner: Dict[Tuple[str, str, str, str], Dict[str, Any]], stored_rows: Sequence[Dict[str, Any]]
) -> None:
    """Add rows stored for the days of a month to the totals of each user, agent, team or workflow and parent."""
    for row in stored_rows:
        bucket_key = (row["user_id"], row["component_type"], row["component_id"], row["parent_component_id"])
        bucket = per_owner.setdefault(bucket_key, empty_os_metrics_totals())
        add_os_metrics_totals(bucket, row)


def calculate_month_os_metrics(
    month_start: date, per_owner: Dict[Tuple[str, str, str, str], Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Calculate the rows of agno_os_metrics of a completed month from the totals of its days.

    A completed day is never rebuilt, so a month of completed days never changes and its rows are
    written once.

    Args:
        month_start (date): The first day of the month.
        per_owner (Dict[Tuple[str, str, str, str], Dict[str, Any]]): The totals of each user, agent, team or
            workflow and parent, added up by add_month_os_metrics.

    Returns:
        List[Dict[str, Any]]: One row per user, agent, team or workflow and parent.
    """
    current_time = int(time.time())

    records: List[dict] = []
    for (user_id, component_type, component_id, parent_component_id), bucket in sorted(per_owner.items()):
        records.append(
            {
                "aggregation_period": "monthly",
                "date": month_start,
                "user_id": user_id,
                "component_type": component_type,
                "component_id": component_id,
                "parent_component_id": parent_component_id,
                "sessions_count": bucket["sessions_count"],
                "runs_count": bucket["runs_count"],
                "input_tokens": bucket["input_tokens"],
                "output_tokens": bucket["output_tokens"],
                "total_tokens": bucket["total_tokens"],
                "duration_runs_count": bucket["duration_runs_count"],
                "time_to_first_token_runs_count": bucket["time_to_first_token_runs_count"],
                "model_calls_count": bucket["model_calls_count"],
                "total_duration_ms": bucket["total_duration_ms"],
                "total_time_to_first_token_ms": bucket["total_time_to_first_token_ms"],
                "total_model_call_ms": bucket["total_model_call_ms"],
                "max_duration_ms": bucket["max_duration_ms"],
                "max_time_to_first_token_ms": bucket["max_time_to_first_token_ms"],
                "max_model_call_ms": bucket["max_model_call_ms"],
                "status_metrics": bucket["status_metrics"],
                "additional_token_metrics": bucket["additional_token_metrics"],
                "duration_buckets": bucket["duration_buckets"],
                "time_to_first_token_buckets": bucket["time_to_first_token_buckets"],
                "model_call_buckets": bucket["model_call_buckets"],
                "model_metrics": bucket["model_metrics"],
                "additional_metrics": bucket["additional_metrics"],
                "buckets_version": OS_METRICS_BUCKETS_VERSION,
                "created_at": current_time,
                "updated_at": current_time,
            }
        )

    return records


def os_metrics_days_to_read(starting_date: date, ending_date: date, month_starts: Sequence[date]) -> List[date]:
    """The days of the date range that are not read from the rows of one of the given months."""
    days_diff = (ending_date - starting_date).days + 1
    days = [starting_date + timedelta(days=x) for x in range(days_diff)]
    return [day for day in days if day.replace(day=1) not in month_starts]


def os_metrics_day_ranges(days: Sequence[date]) -> List[Tuple[date, date]]:
    """Group days, oldest first, into the first and last day of every run of consecutive days."""
    ranges: List[Tuple[date, date]] = []
    for day in days:
        if ranges and day - ranges[-1][1] == timedelta(days=1):
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return ranges


def os_metrics_versions(rows: Sequence[Any]) -> Dict[str, int]:
    """The version of each totals row, keyed by its aggregation period and date.

    Each row holds its aggregation_period, date and version, as attributes or as the keys of a dict.
    """
    versions: Dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            versions[f"{row['aggregation_period']} {row['date'].isoformat()}"] = row["version"]
        else:
            versions[f"{row.aggregation_period} {row.date.isoformat()}"] = row.version
    return versions


def build_os_metrics_totals(
    fields: Sequence[str], rows: Sequence[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Build the OS metrics totals of each date from the stored rows of those dates.

    Args:
        fields (Sequence[str]): The columns to total.
        rows (Sequence[Dict[str, Any]]): The rows of agno_os_metrics or agno_os_metrics_totals, their date a date.

    Returns:
        Tuple[List[Dict[str, Any]], Optional[int]]: One dict per date, oldest first, and when the rows were
            last updated. A month totalled from its month rows is one dict, dated its first day.
    """
    rows_by_date: Dict[date, List[Dict[str, Any]]] = {}
    latest_updated_at: Optional[int] = None
    for row in rows:
        if "additional_metrics" in fields:
            # Only the numbers of additional_metrics are totalled; the rest keeps no meaning across rows
            row = dict(row)
            row["additional_metrics"] = {
                key: value
                for key, value in (row.get("additional_metrics") or {}).items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
        rows_by_date.setdefault(row["date"], []).append(row)
        if row.get("updated_at") is not None and (latest_updated_at is None or row["updated_at"] > latest_updated_at):
            latest_updated_at = row["updated_at"]

    totals = []
    for row_date in sorted(rows_by_date):
        day_totals: Dict[str, Any] = {"date": row_date}
        day_totals.update(merge_os_metrics_totals(rows_by_date[row_date], fields))
        totals.append(day_totals)
    return totals, latest_updated_at


def deserialize_os_metrics_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the stored OS metrics rows with their date as a date, as calculate_date_os_metrics builds them.

    Args:
        rows (List[Dict[str, Any]]): The rows as stored, their date an ISO string.

    Returns:
        List[Dict[str, Any]]: The rows with their date as a date.
    """
    return [{**row, "date": datetime.strptime(row["date"], "%Y-%m-%d").date()} for row in rows]


def get_os_metrics_records_by_day(
    records: List[Dict[str, Any]], start_timestamp: int, end_timestamp: int
) -> Dict[date, List[Dict[str, Any]]]:
    """Return the sessions or runs created in the given time range, by the UTC day they were created on.

    Args:
        records (List[Dict[str, Any]]): The sessions or the runs.
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


def get_os_metrics_rows_by_key(
    rows: List[Dict[str, Any]], key_columns: Sequence[str] = OS_METRICS_KEY_COLUMNS
) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
    """Return the OS metrics rows keyed by the columns they are unique by, in their stored order.

    Args:
        rows (List[Dict[str, Any]]): The rows of agno_os_metrics, or of agno_os_metrics_totals.
        key_columns (Sequence[str]): OS_METRICS_KEY_COLUMNS, or OS_METRICS_TOTALS_KEY_COLUMNS.

    Returns:
        Dict[Tuple[Any, ...], Dict[str, Any]]: The rows by key.
    """
    return {tuple(row[column] for column in key_columns): row for row in rows}


def bulk_upsert_os_metrics(
    rows_by_key: Dict[Tuple[Any, ...], Dict[str, Any]], os_metrics_records: List[Dict[str, Any]]
) -> None:
    """Bulk upsert OS metrics into the stored rows, in place.

    Args:
        rows_by_key (Dict[Tuple[Any, ...], Dict[str, Any]]): The stored rows, from get_os_metrics_rows_by_key.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
    """
    for record in os_metrics_records:
        key = tuple(record[column] for column in OS_METRICS_KEY_COLUMNS)
        stored = rows_by_key.get(key)
        # The key and created_at of a stored row are never overwritten
        rows_by_key[key] = record if stored is None else {**record, "created_at": stored.get("created_at")}


def upsert_os_metrics_totals_row(
    totals_by_key: Dict[Tuple[Any, ...], Dict[str, Any]], totals_row: Dict[str, Any]
) -> None:
    """Upsert an OS metrics totals row into the stored total rows, in place.

    A new row starts at version 1, and every write of a stored one moves its version by one.

    Args:
        totals_by_key (Dict[Tuple[Any, ...], Dict[str, Any]]): The stored total rows, from
            get_os_metrics_rows_by_key.
        totals_row (Dict[str, Any]): The row, from build_os_metrics_totals_row.
    """
    key = tuple(totals_row[column] for column in OS_METRICS_TOTALS_KEY_COLUMNS)
    stored = totals_by_key.get(key)
    if stored is None:
        totals_by_key[key] = {**totals_row, "version": 1}
    else:
        totals_by_key[key] = {**totals_row, "created_at": stored.get("created_at"), "version": stored["version"] + 1}


def total_os_metrics_rows(
    rows: List[Dict[str, Any]],
    starting_date: date,
    ending_date: date,
    user_id: Optional[str],
    fields: Sequence[str],
    month_starts: Sequence[date] = (),
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Total the OS metrics rows of each date in the given date range.

    Args:
        rows (List[Dict[str, Any]]): The total rows to total every user, or the OS metrics rows to total one.
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        user_id (Optional[str]): The user whose OS metrics rows are totalled. ``None`` for the total rows.
        fields (Sequence[str]): The columns to total.
        month_starts (Sequence[date]): The first day of every month inside the date range to total from its month
            row instead of its days.

    Returns:
        Tuple[List[Dict[str, Any]], Optional[int]]: One dict per date, oldest first, and when the rows were last
            updated. A month totalled from its month row is one dict, dated its first day.
    """
    days = set(os_metrics_days_to_read(starting_date, ending_date, month_starts))
    return build_os_metrics_totals(
        fields,
        [
            row
            for row in rows
            if (user_id is None or row["user_id"] == user_id)
            and (
                (row["aggregation_period"] == "daily" and row["date"] in days)
                or (row["aggregation_period"] == "monthly" and row["date"] in month_starts)
            )
        ],
    )


def os_metrics_percentile(buckets: Dict[str, int], fraction: float, max_ms: Optional[int] = None) -> Optional[int]:
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
    for bound in _OS_METRICS_BUCKET_BOUNDS_MS:
        count = buckets.get(f"le_{bound}", 0)
        if count and counted + count >= target:
            value = round(lower_bound + (bound - lower_bound) * (target - counted) / count)
            return value if max_ms is None else min(value, max_ms)
        counted += count
        lower_bound = bound
    # Past the last bound only the slowest timing recorded says how far the tail goes
    return _OS_METRICS_BUCKET_BOUNDS_MS[-1] if max_ms is None else max(max_ms, _OS_METRICS_BUCKET_BOUNDS_MS[-1])


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
