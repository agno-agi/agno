"""Logic shared across different database implementations"""

import json
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, Optional, Union
from uuid import UUID

from agno.metrics import ModelMetrics, RunMetrics, SessionMetrics
from agno.models.message import Message
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.registry.registry import Registry


# Keys in a serialized db dict that correspond to table-name overrides.
# Matches the parameters BaseDb.__init__ accepts for customizing table names.
DB_TABLE_NAME_KEYS: frozenset = frozenset(
    {
        "session_table",
        "culture_table",
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
    }
)


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
        data (dict): The dictionary to serialize JSON fields in.

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

    try:
        from agno.db.postgres import PostgresDb

        if isinstance(source_db, PostgresDb):
            return PostgresDb(
                db_url=source_db.db_url,
                db_engine=source_db.db_engine,
                db_schema=source_db.db_schema,
                id=source_db.id,
                **overrides,
            )
    except Exception as e:
        log_error(f"Error cloning PostgresDb with table overrides: {str(e)}")
        return None

    try:
        from agno.db.sqlite import SqliteDb

        if isinstance(source_db, SqliteDb):
            return SqliteDb(
                db_file=source_db.db_file,
                db_url=source_db.db_url,
                db_engine=source_db.db_engine,
                id=source_db.id,
                **overrides,
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
