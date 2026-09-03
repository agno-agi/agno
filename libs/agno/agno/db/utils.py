"""Logic shared across different database implementations"""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union
from uuid import UUID

from agno.exceptions import MigrationRequiredError, SchemaMismatchError
from agno.metrics import ModelMetrics, RunMetrics, SessionMetrics
from agno.models.message import Message
from agno.run.base import HISTORY_SKIP_STATUSES as _RUN_HISTORY_SKIP_STATUSES
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


def serialize_session_json_fields(session: dict) -> dict:
    """Serialize all JSON fields in the given Session dictionary.

    Uses CustomJSONEncoder to handle non-JSON-serializable types like
    datetime, date, UUID, Message, Metrics, etc.

    Args:
        session (dict): The session dictionary to serialize JSON fields in.

    Returns:
        dict: The dictionary with JSON fields serialized.
    """
    if session.get("session_data") is not None:
        session["session_data"] = json.dumps(session["session_data"], cls=CustomJSONEncoder)
    if session.get("agent_data") is not None:
        session["agent_data"] = json.dumps(session["agent_data"], cls=CustomJSONEncoder)
    if session.get("team_data") is not None:
        session["team_data"] = json.dumps(session["team_data"], cls=CustomJSONEncoder)
    if session.get("workflow_data") is not None:
        session["workflow_data"] = json.dumps(session["workflow_data"], cls=CustomJSONEncoder)
    if session.get("metadata") is not None:
        session["metadata"] = json.dumps(session["metadata"], cls=CustomJSONEncoder)
    if session.get("chat_history") is not None:
        session["chat_history"] = json.dumps(session["chat_history"], cls=CustomJSONEncoder)
    if session.get("summary") is not None:
        session["summary"] = json.dumps(session["summary"], cls=CustomJSONEncoder)
    if session.get("runs") is not None:
        session["runs"] = json.dumps(session["runs"], cls=CustomJSONEncoder)

    return session


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


def db_from_dict(db_data: Dict[str, Any]) -> Optional[Union["BaseDb"]]:
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
) -> Optional["BaseDb"]:
    """Resolve a serialized db config to a concrete ``BaseDb`` instance.

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
        A ``BaseDb`` instance, or ``None`` if reconstruction fails.
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
