"""Table schemas and related utilities used by the OracleDb class.

Mirrors ``agno.db.postgres.schemas`` table for table and column for column.
Two things cannot simply be copied over, because Oracle has no equivalent:

* Postgres's ``JSONB`` becomes one of two custom types depending on the
  server's detected capabilities (see ``_version.py``): a native ``JSON``
  column on 21c and later, or a ``CLOB`` with an ``IS JSON`` check constraint
  below that. Both round-trip Python values through the same JSON
  serialization agno's other SQL adapters use.
* Postgres's bare ``String`` (unbounded, since Postgres does not require a
  declared length) becomes ``VARCHAR2(n CHAR)`` for every indexed, keyed or
  otherwise short column, and ``CLOB`` for genuinely free-form content that
  was already ``Text`` on Postgres. Widths live in the named constants below,
  not as literals scattered across each table's dict, so a width decision is
  made once and applies everywhere that column shape recurs. ``CHAR``
  semantics are mandatory, not a tuning choice: with an AL32UTF8 database
  character set, a 255-character accented name can occupy up to 1020 bytes,
  and a byte-counted column would reject it with ORA-12899.

``BigInteger``, ``Integer``, ``Date`` and ``Text`` need no substitution: the
Oracle dialect already compiles them to ``NUMBER(19)``, ``NUMBER(10)``,
``DATE`` and ``CLOB`` respectively.
"""

import json
from decimal import Decimal
from functools import partial
from typing import Any, Dict, List, Optional

from sqlalchemy.dialects import oracle
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger, Boolean, Date, Integer, String, Text, TypeDecorator

from agno.db.oracle._version import OracleCapabilities
from agno.db.schemas.mcp_oauth import MCP_OAUTH_TABLE_SCHEMAS
from agno.db.utils import json_serializer

# -- Column widths --
#
# One named constant per semantic role, so a width decision is recorded once.
# WIDTH_ID, WIDTH_NAME, WIDTH_STATUS and WIDTH_ENUM reuse the values already
# validated by the MySQL adapter (the only other backend forced to declare
# column widths); the rest are derived from the columns that actually need
# them and recorded here.
WIDTH_ID = 128  # session_id, run_id, agent_id, user_id, and every other identifier column
WIDTH_NAME = 255  # display names: session name, schedule name, service account name
WIDTH_STATUS = 50  # status columns: run status, approval status, job status
WIDTH_ENUM = 20  # short fixed-vocabulary columns: session_type, run_type, http method
WIDTH_VERSION_STR = 10  # a schema version string such as "3.0.0"
WIDTH_ISO_TIMESTAMP = 128  # an ISO 8601 datetime string (traces/spans store these as text)
WIDTH_HASH = 128  # digests: content_hash, args_hash, token_hash (room well beyond SHA-256 hex)
WIDTH_URL = 2000  # endpoint URLs, external ids
WIDTH_LABEL = 255  # component config label, stage, link_kind, link_key
WIDTH_TIMEZONE = 64  # IANA timezone names (the longest are ~40 characters)


def varchar(width: int) -> String:
    """VARCHAR2(n CHAR) -- never the default byte semantics.

    Used for every column that is indexed, keyed, or otherwise short; a
    generic ``Text``/``CLOB`` is used instead for genuinely free-form content
    (matching what was already ``Text`` rather than ``String`` on Postgres).
    """
    return String(width).with_variant(oracle.VARCHAR2(width, "CHAR"), "oracle")


# -- JSON, in the variant the connected server actually supports --
#
# Both types serialize through the same json_serializer every other agno SQL
# adapter uses (handles datetime, date, UUID, etc.), and both defensively
# accept an already-decoded value on read: python-oracledb's thin driver can
# hand a native JSON column back as an already-decoded dict/list rather than
# text, so process_result_value must not assume a string.
def _replace_decimals(value: Any) -> Any:
    """Recursively convert Decimal to int/float in a decoded JSON value.

    python-oracledb's thin driver decodes a native JSON column's numbers to
    ``decimal.Decimal`` rather than int/float (confirmed against a live
    server: a run's ``run_index`` came back as a Decimal). ``Decimal`` is not
    JSON-serializable, so any caller that re-serializes a value read from
    here -- the run-object cache building its raw-text cache key, for one --
    fails with ``TypeError: Object of type Decimal is not JSON serializable``.
    Converting at the point of decode, once, is simpler than teaching every
    downstream re-serialization call about this Oracle-specific quirk.
    """
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if as_int == value else float(value)
    if isinstance(value, dict):
        return {k: _replace_decimals(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_decimals(v) for v in value]
    return value


def _decode_native_json(value: Any) -> Any:
    """Decode a value read from a native Oracle JSON column.

    python-oracledb's thin driver fully decodes a native JSON scalar to its
    Python equivalent -- not just dict/list, but str, int, float, bool and
    None too -- so a plain Python string here is already the decoded value,
    never JSON-encoded text still awaiting ``json.loads``. Confirmed against
    a live server: a memory's ``memory`` field (a bare string) came back as
    exactly that string, and calling ``json.loads`` on it raised
    (``Expecting value: line 1 column 1``), because unquoted text is not
    valid JSON on its own. This is the opposite of ``OracleClobJSON``, whose
    physical column really is text and must always be parsed.
    """
    return _replace_decimals(value)


def _decode_clob_json(value: Any) -> Any:
    """Decode a value read from the CLOB + IS JSON check column variant.

    Unlike the native JSON column, this physical column is always text (or a
    LOB proxy for content the driver did not inline), so it always needs
    ``json.loads`` -- there is no driver-side auto-decoding here.
    """
    if value is None:
        return None
    if hasattr(value, "read"):  # a LOB proxy, when the driver does not inline small CLOBs
        value = value.read()
    return _replace_decimals(json.loads(value))


class OracleNativeJSON(TypeDecorator):
    """Native Oracle JSON column. Requires 21c or later."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        return None if value is None else json_serializer(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return _decode_native_json(value)


@compiles(OracleNativeJSON, "oracle")
def _compile_oracle_native_json(element: Any, compiler: Any, **kw: Any) -> str:
    return "JSON"


class OracleClobJSON(TypeDecorator):
    """CLOB storage for JSON, used below 21c where no native JSON type exists.

    Renders as bare CLOB, with no ``IS JSON`` check constraint at all -- not
    merely as a workaround for the inline-check restriction (Oracle rejects a
    column-level CHECK that names any column, including itself: ORA-02438,
    "Column check constraint cannot reference other columns"), but because an
    out-of-line one is not usable here either. Oracle's ``IS JSON`` on these
    releases predates RFC 7159 and accepts only a JSON object or array at the
    top level; agno stores plain scalars in some columns typed as JSON here
    (a memory's ``memory`` field is a bare string), and every one of those
    inserts would be rejected outright (ORA-02290, confirmed against a live
    18c server: an array and an object both pass ``IS JSON``, a quoted string
    does not, with no parameter -- ``STRICT``, ``LAX`` -- that changes this).
    Validation for this storage variant is therefore the adapter's own
    serialize/deserialize round trip, not a database-level structural check;
    the native JSON variant (21c and later) does not have this gap, since the
    column's own type enforces JSON-ness for any value, scalars included.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        return None if value is None else json_serializer(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return _decode_clob_json(value)


class OracleNativeBoolean(TypeDecorator):
    """Native Oracle BOOLEAN column. Requires 23ai or later.

    Below 23ai, plain ``sqlalchemy.types.Boolean`` is used instead: the
    Oracle dialect already emulates it as NUMBER(1), which needs no variant
    of its own.
    """

    impl = Boolean
    cache_ok = True


@compiles(OracleNativeBoolean, "oracle")
def _compile_oracle_native_boolean(element: Any, compiler: Any, **kw: Any) -> str:
    return "BOOLEAN"


def json_type(capabilities: OracleCapabilities) -> type:
    """The JSON column type class for this server's detected capabilities."""
    return OracleNativeJSON if capabilities.native_json else OracleClobJSON


def boolean_type(capabilities: OracleCapabilities) -> type:
    """The boolean column type class for this server's detected capabilities."""
    return OracleNativeBoolean if capabilities.native_boolean else Boolean


def _qualify(db_schema: Optional[str], name: str) -> str:
    """Schema-qualify ``name`` only when a schema was actually given.

    On Oracle a schema is a user (see the adapter's ``db_schema`` handling):
    the default is None, meaning "the connecting user's own schema", and
    tables are created unqualified. A foreign key reference must match that
    -- qualifying it unconditionally the way the Postgres schema module does
    would reference a schema that was never used to create the parent table.
    """
    return f"{db_schema}.{name}" if db_schema else name


def get_session_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    json_col = json_type(capabilities)
    return {
        "session_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "session_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        "agent_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "team_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "workflow_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "session_data": {"type": json_col, "nullable": True},
        "agent_data": {"type": json_col, "nullable": True},
        "team_data": {"type": json_col, "nullable": True},
        "workflow_data": {"type": json_col, "nullable": True},
        "metadata": {"type": json_col, "nullable": True},
        "summary": {"type": json_col, "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
    }


def _get_run_table_schema(
    capabilities: OracleCapabilities, session_table_name: str = "agno_sessions", db_schema: Optional[str] = None
) -> Dict[str, Any]:
    """Runs table schema; ``session_id`` foreign-keyed to sessions with
    ON DELETE CASCADE.

    Factory (not a module-level dict), matching the Postgres module: the FK
    reference binds to the caller-configured session table name at build time.
    """
    return {
        "run_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "session_id": {
            "type": partial(varchar, WIDTH_ID),
            "nullable": False,
            "index": True,
            "foreign_key": _qualify(db_schema, f"{session_table_name}.session_id"),
            "ondelete": "CASCADE",
        },
        "run_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        "agent_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "team_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "workflow_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "parent_run_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "status": {"type": partial(varchar, WIDTH_STATUS), "nullable": True, "index": True},
        "run_index": {"type": BigInteger, "nullable": True},
        "run_data": {"type": json_type(capabilities), "nullable": False},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "__composite_indexes__": [
            {"name": "agno_runs_session_id_run_index", "columns": ["session_id", "run_index"]},
        ],
    }


def get_memory_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    return {
        "memory_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "memory": {"type": json_type(capabilities), "nullable": False},
        "feedback": {"type": Text, "nullable": True},
        "input": {"type": Text, "nullable": True},
        "agent_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "team_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "topics": {"type": json_type(capabilities), "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True, "index": True},
    }


def get_eval_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    json_col = json_type(capabilities)
    return {
        "run_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "eval_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False},
        "eval_data": {"type": json_col, "nullable": False},
        "eval_input": {"type": json_col, "nullable": False},
        "name": {"type": partial(varchar, WIDTH_NAME), "nullable": True},
        "agent_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "team_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "workflow_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "model_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "model_provider": {"type": partial(varchar, WIDTH_ENUM), "nullable": True},
        "evaluated_component_name": {"type": partial(varchar, WIDTH_NAME), "nullable": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
    }


def get_knowledge_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    return {
        "id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "name": {"type": partial(varchar, WIDTH_NAME), "nullable": False},
        "description": {"type": Text, "nullable": False},
        "metadata": {"type": json_type(capabilities), "nullable": True},
        "type": {"type": partial(varchar, WIDTH_ENUM), "nullable": True},
        "size": {"type": BigInteger, "nullable": True},
        "linked_to": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "access_count": {"type": BigInteger, "nullable": True},
        "status": {"type": partial(varchar, WIDTH_STATUS), "nullable": True},
        "status_message": {"type": Text, "nullable": True},
        "created_at": {"type": BigInteger, "nullable": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "external_id": {"type": partial(varchar, WIDTH_URL), "nullable": True},
        # Uploader. NULL means shared: visible to every user.
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "__composite_indexes__": [
            {"name": "ix_knowledge_user_linked_to", "columns": ["user_id", "linked_to"]},
        ],
    }


def get_metrics_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    json_col = json_type(capabilities)
    return {
        "id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "agent_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
        "team_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
        "workflow_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
        "agent_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
        "team_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
        "workflow_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
        "users_count": {"type": BigInteger, "nullable": False, "default": 0},
        "token_metrics": {"type": json_col, "nullable": False, "default": {}},
        "model_metrics": {"type": json_col, "nullable": False, "default": {}},
        "date": {"type": Date, "nullable": False, "index": True},
        "aggregation_period": {"type": partial(varchar, WIDTH_ENUM), "nullable": False},
        # Owner of this bucket. The sentinel from utils.py stands in for the
        # unowned bucket at rest (Oracle folds "" to NULL, which would
        # otherwise collide with the unfiltered-read meaning of NULL); the
        # column stays declared NOT NULL with the same empty-string default
        # semantics as Postgres, translated at the adapter boundary.
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": False, "default": "", "index": True},
        "created_at": {"type": BigInteger, "nullable": False},
        "updated_at": {"type": BigInteger, "nullable": True},
        "completed": {"type": boolean_type(capabilities), "nullable": False, "default": False},
        "_unique_constraints": [
            {"name": "uq_metrics_user_date_period", "columns": ["user_id", "date", "aggregation_period"]}
        ],
    }


def get_versions_table_schema() -> Dict[str, Any]:
    return {
        "table_name": {"type": partial(varchar, WIDTH_ID), "nullable": False, "primary_key": True},
        "version": {"type": partial(varchar, WIDTH_VERSION_STR), "nullable": False},
        "created_at": {"type": partial(varchar, WIDTH_ISO_TIMESTAMP), "nullable": False, "index": True},
        "updated_at": {"type": partial(varchar, WIDTH_ISO_TIMESTAMP), "nullable": True},
    }


def get_trace_table_schema() -> Dict[str, Any]:
    return {
        "trace_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "name": {"type": partial(varchar, WIDTH_NAME), "nullable": False},
        "status": {"type": partial(varchar, WIDTH_STATUS), "nullable": False, "index": True},
        "start_time": {"type": partial(varchar, WIDTH_ISO_TIMESTAMP), "nullable": False, "index": True},
        "end_time": {"type": partial(varchar, WIDTH_ISO_TIMESTAMP), "nullable": False},
        "duration_ms": {"type": BigInteger, "nullable": False},
        "run_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "session_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "agent_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "team_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "workflow_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "created_at": {"type": partial(varchar, WIDTH_ISO_TIMESTAMP), "nullable": False, "index": True},
    }


def _get_span_table_schema(
    capabilities: OracleCapabilities,
    traces_table_name: str = "agno_traces",
    db_schema: Optional[str] = None,
) -> Dict[str, Any]:
    """Span table schema with the correct foreign key reference to traces."""
    return {
        "span_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "trace_id": {
            "type": partial(varchar, WIDTH_ID),
            "nullable": False,
            "index": True,
            "foreign_key": _qualify(db_schema, f"{traces_table_name}.trace_id"),
        },
        "parent_span_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "name": {"type": partial(varchar, WIDTH_NAME), "nullable": False},
        "span_kind": {"type": partial(varchar, WIDTH_ENUM), "nullable": False},
        "status_code": {"type": partial(varchar, WIDTH_STATUS), "nullable": False},
        "status_message": {"type": Text, "nullable": True},
        "start_time": {"type": partial(varchar, WIDTH_ISO_TIMESTAMP), "nullable": False, "index": True},
        "end_time": {"type": partial(varchar, WIDTH_ISO_TIMESTAMP), "nullable": False},
        "duration_ms": {"type": BigInteger, "nullable": False},
        "attributes": {"type": json_type(capabilities), "nullable": True},
        "created_at": {"type": partial(varchar, WIDTH_ISO_TIMESTAMP), "nullable": False, "index": True},
    }


def get_component_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    return {
        "component_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True},
        "component_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        "name": {"type": partial(varchar, WIDTH_NAME), "nullable": True, "index": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "description": {"type": Text, "nullable": True},
        "current_version": {"type": Integer, "nullable": True, "index": True},
        "metadata": {"type": json_type(capabilities), "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "deleted_at": {"type": BigInteger, "nullable": True},
    }


def get_component_configs_table_schema(
    capabilities: OracleCapabilities, components_table_name: str = "agno_components", db_schema: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "component_id": {
            "type": partial(varchar, WIDTH_ID),
            "primary_key": True,
            "foreign_key": _qualify(db_schema, f"{components_table_name}.component_id"),
        },
        "version": {"type": Integer, "primary_key": True},
        "label": {"type": partial(varchar, WIDTH_LABEL), "nullable": True},
        "stage": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "default": "draft", "index": True},
        "config": {"type": json_type(capabilities), "nullable": False},
        "notes": {"type": Text, "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "deleted_at": {"type": BigInteger, "nullable": True},
    }


def get_component_links_table_schema(
    capabilities: OracleCapabilities,
    components_table_name: str = "agno_components",
    component_configs_table_name: str = "agno_component_configs",
    db_schema: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "parent_component_id": {"type": partial(varchar, WIDTH_ID), "nullable": False},
        "parent_version": {"type": Integer, "nullable": False},
        "link_kind": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        "link_key": {"type": partial(varchar, WIDTH_LABEL), "nullable": False},
        "child_component_id": {
            "type": partial(varchar, WIDTH_ID),
            "nullable": False,
            "foreign_key": _qualify(db_schema, f"{components_table_name}.component_id"),
        },
        "child_version": {"type": Integer, "nullable": True},
        "position": {"type": Integer, "nullable": False},
        "meta": {"type": json_type(capabilities), "nullable": True},
        "created_at": {"type": BigInteger, "nullable": True, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "__primary_key__": ["parent_component_id", "parent_version", "link_kind", "link_key"],
        "__foreign_keys__": [
            {
                "columns": ["parent_component_id", "parent_version"],
                "ref_table": component_configs_table_name,
                "ref_columns": ["component_id", "version"],
            }
        ],
    }


def get_learnings_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    json_col = json_type(capabilities)
    return {
        "learning_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "learning_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        "namespace": {"type": partial(varchar, WIDTH_NAME), "nullable": True, "index": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "agent_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "team_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "workflow_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "session_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "entity_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "entity_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": True, "index": True},
        "content": {"type": json_col, "nullable": False},
        "metadata": {"type": json_col, "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
    }


def get_schedule_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    return {
        "id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "name": {"type": partial(varchar, WIDTH_NAME), "nullable": False, "index": True},
        "description": {"type": Text, "nullable": True},
        "method": {"type": partial(varchar, WIDTH_ENUM), "nullable": False},
        "endpoint": {"type": partial(varchar, WIDTH_URL), "nullable": False},
        "payload": {"type": json_type(capabilities), "nullable": True},
        "cron_expr": {"type": partial(varchar, WIDTH_NAME), "nullable": False},
        "timezone": {"type": partial(varchar, WIDTH_TIMEZONE), "nullable": False},
        "timeout_seconds": {"type": BigInteger, "nullable": False},
        "max_retries": {"type": BigInteger, "nullable": False},
        "retry_delay_seconds": {"type": BigInteger, "nullable": False},
        "enabled": {"type": boolean_type(capabilities), "nullable": False, "default": True},
        "next_run_at": {"type": BigInteger, "nullable": True, "index": True},
        "locked_by": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "locked_at": {"type": BigInteger, "nullable": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "managed_by": {"type": partial(varchar, WIDTH_ENUM), "nullable": True, "index": True},
        "target_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": True},
        "target_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "created_by_run_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "created_by_session_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "updated_by_run_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "updated_by_session_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "disabled_reason": {"type": partial(varchar, WIDTH_NAME), "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "__composite_indexes__": [
            {"name": "enabled_next_run_at", "columns": ["enabled", "next_run_at"]},
            {"name": "user_enabled_next_run_at", "columns": ["user_id", "enabled", "next_run_at"]},
        ],
        # Oracle has no partial index; these become unique function-based
        # indexes (see partial_unique_index_elements in utils.py). The
        # predicate text is identical to Postgres's -- portable SQL, no
        # dialect-specific syntax.
        "_partial_unique_indexes": [
            {"name": "uq_user_name", "columns": ["user_id", "name"], "where": "user_id IS NOT NULL"},
            {"name": "uq_unowned_name", "columns": ["name"], "where": "user_id IS NULL"},
        ],
    }


def _get_schedule_runs_table_schema(
    capabilities: OracleCapabilities,
    schedules_table_name: str = "agno_schedules",
    db_schema: Optional[str] = None,
) -> Dict[str, Any]:
    json_col = json_type(capabilities)
    return {
        "id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "schedule_id": {
            "type": partial(varchar, WIDTH_ID),
            "nullable": False,
            "index": True,
            "foreign_key": _qualify(db_schema, f"{schedules_table_name}.id"),
            "ondelete": "CASCADE",
        },
        "attempt": {"type": BigInteger, "nullable": False},
        "triggered_at": {"type": BigInteger, "nullable": True},
        "completed_at": {"type": BigInteger, "nullable": True},
        "status": {"type": partial(varchar, WIDTH_STATUS), "nullable": False, "index": True},
        "status_code": {"type": BigInteger, "nullable": True},
        "run_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "session_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "error": {"type": Text, "nullable": True},
        "input": {"type": json_col, "nullable": True},
        "output": {"type": json_col, "nullable": True},
        "requirements": {"type": json_col, "nullable": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
    }


def get_tool_results_table_schema() -> Dict[str, Any]:
    return {
        "result_id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "namespace": {"type": partial(varchar, WIDTH_NAME), "nullable": False},
        "path": {"type": partial(varchar, WIDTH_URL), "nullable": False},
        "session_id": {"type": partial(varchar, WIDTH_ID), "nullable": False},
        "run_id": {"type": partial(varchar, WIDTH_ID), "nullable": False},
        "tool_call_id": {"type": partial(varchar, WIDTH_ID), "nullable": False},
        "tool_name": {"type": partial(varchar, WIDTH_NAME), "nullable": False},
        "args_hash": {"type": partial(varchar, WIDTH_HASH), "nullable": False},
        "content_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False},
        "size_bytes": {"type": BigInteger, "nullable": False},
        "line_count": {"type": BigInteger, "nullable": False},
        "preview": {"type": Text, "nullable": False},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False},
        "expires_at": {"type": BigInteger, "nullable": True, "index": True},
        "_unique_constraints": [
            {"name": "uq_tool_results_namespace_path", "columns": ["namespace", "path"]},
        ],
        "__composite_indexes__": [
            {"name": "session_created_at", "columns": ["session_id", "created_at"]},
        ],
    }


def get_jobs_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    return {
        "id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "component_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False},
        "job_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False},
        "deployment_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "component_id": {"type": partial(varchar, WIDTH_ID), "nullable": False, "index": True},
        "session_id": {"type": partial(varchar, WIDTH_ID), "nullable": False, "index": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "payload": {"type": json_type(capabilities), "nullable": False},
        "status": {"type": partial(varchar, WIDTH_STATUS), "nullable": False, "index": True},
        "attempt": {"type": BigInteger, "nullable": False},
        "max_attempts": {"type": BigInteger, "nullable": False},
        "idempotency_key": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "available_at": {"type": BigInteger, "nullable": False},
        "locked_by": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "locked_at": {"type": BigInteger, "nullable": True},
        "error": {"type": Text, "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "completed_at": {"type": BigInteger, "nullable": True},
        "__composite_indexes__": [
            {"name": "status_available_at", "columns": ["status", "available_at"]},
        ],
        "_partial_unique_indexes": [
            {
                "name": "uq_jobs_idempotency_key",
                "columns": ["idempotency_key", "user_id"],
                "where": "idempotency_key IS NOT NULL",
            },
            {
                "name": "uq_jobs_idempotency_key_anon",
                "columns": ["idempotency_key"],
                "where": "idempotency_key IS NOT NULL AND user_id IS NULL",
            },
        ],
    }


def get_approval_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    json_col = json_type(capabilities)
    return {
        "id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "run_id": {"type": partial(varchar, WIDTH_ID), "nullable": False, "index": True},
        "session_id": {"type": partial(varchar, WIDTH_ID), "nullable": False, "index": True},
        "status": {"type": partial(varchar, WIDTH_STATUS), "nullable": False, "index": True},
        "source_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        "approval_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": True, "index": True},
        "pause_type": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        "tool_name": {"type": partial(varchar, WIDTH_NAME), "nullable": True},
        "tool_args": {"type": json_col, "nullable": True},
        "expires_at": {"type": BigInteger, "nullable": True},
        "agent_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "team_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "workflow_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "schedule_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "schedule_run_id": {"type": partial(varchar, WIDTH_ID), "nullable": True, "index": True},
        "source_name": {"type": partial(varchar, WIDTH_NAME), "nullable": True},
        "requirements": {"type": json_col, "nullable": True},
        "context": {"type": json_col, "nullable": True},
        "resolution_data": {"type": json_col, "nullable": True},
        "resolved_by": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "resolved_at": {"type": BigInteger, "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "run_status": {"type": partial(varchar, WIDTH_STATUS), "nullable": True, "index": True},
    }


def get_auth_token_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    json_col = json_type(capabilities)
    return {
        "id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "provider": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        # Empty string for single-user mode; translated at the adapter
        # boundary to the shared owner sentinel (see utils.py).
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": False, "index": True},
        "service": {"type": partial(varchar, WIDTH_ENUM), "nullable": False, "index": True},
        "token_data": {"type": json_col, "nullable": False},
        "granted_scopes": {"type": json_col, "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        "_unique_constraints": [
            {"name": "uq_auth_token_provider_user_service", "columns": ["provider", "user_id", "service"]}
        ],
    }


def get_service_account_table_schema(capabilities: OracleCapabilities) -> Dict[str, Any]:
    return {
        "id": {"type": partial(varchar, WIDTH_ID), "primary_key": True, "nullable": False},
        "name": {"type": partial(varchar, WIDTH_NAME), "nullable": False},
        "user_id": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "token_hash": {"type": partial(varchar, WIDTH_HASH), "nullable": False, "unique": True, "index": True},
        "token_prefix": {"type": partial(varchar, WIDTH_ENUM), "nullable": False},
        "scopes": {"type": json_type(capabilities), "nullable": False},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "expires_at": {"type": BigInteger, "nullable": True},
        "last_used_at": {"type": BigInteger, "nullable": True},
        "revoked_at": {"type": BigInteger, "nullable": True},
        "created_by": {"type": partial(varchar, WIDTH_ID), "nullable": True},
        "_partial_unique_indexes": [{"name": "uq_active_name", "columns": ["name"], "where": "revoked_at IS NULL"}],
    }


# Table types this module can produce a schema definition for. Kept in sync
# with get_table_schema_definition's dispatch below -- 20 SQL-adapter tables
# plus the 5 shared MCP OAuth tables.
def _widen_mcp_oauth_schema(schema_def: Dict[str, Any]) -> Dict[str, Any]:
    """Give the shared MCP OAuth schema dict's bare ``String`` columns an
    explicit Oracle width.

    ``agno.db.schemas.mcp_oauth`` is shared with every SQL backend and
    declares its identifier and hash columns as plain ``String`` -- valid,
    unbounded VARCHAR on Postgres, but Oracle requires a declared length on
    VARCHAR2 and rejects the bare form with ORA-00906. That module is not
    ours to edit (mysql and sqlite consume it as-is too); this widens a copy
    of its output for the Oracle dialect only, the same way this module
    already picks JSON and boolean variants for every other table.
    """
    widened = dict(schema_def)
    for col_name, col_config in schema_def.items():
        if col_name.startswith("_"):
            continue
        if col_config.get("type") is String:
            widened[col_name] = {**col_config, "type": partial(varchar, WIDTH_ID)}
    return widened


ALL_TABLE_TYPES: List[str] = [
    "sessions",
    "runs",
    "evals",
    "metrics",
    "memories",
    "knowledge",
    "versions",
    "traces",
    "spans",
    "components",
    "component_configs",
    "component_links",
    "learnings",
    "schedules",
    "schedule_runs",
    "jobs",
    "tool_results",
    "approvals",
    "auth_tokens",
    "service_accounts",
    *MCP_OAUTH_TABLE_SCHEMAS.keys(),
]


def get_table_schema_definition(
    table_type: str,
    capabilities: OracleCapabilities,
    traces_table_name: str = "agno_traces",
    db_schema: Optional[str] = None,
    schedules_table_name: str = "agno_schedules",
    session_table_name: str = "agno_sessions",
    components_table_name: str = "agno_components",
    component_configs_table_name: str = "agno_component_configs",
) -> Dict[str, Any]:
    """Get the expected schema definition for the given table type.

    Args:
        table_type: The type of table to get the schema for.
        capabilities: The connected server's detected (or overridden)
            capabilities, deciding the JSON and boolean column variants.
        traces_table_name: Name of the traces table (spans' foreign key).
        db_schema: The database schema name, or None for the connecting
            user's own schema (see ``_qualify``).
        schedules_table_name: Name of the schedules table (schedule_runs' FK).
        session_table_name: Name of the sessions table (runs' FK).
        components_table_name: Name of the components table (component_configs'
            and component_links' FK).
        component_configs_table_name: Name of the component_configs table
            (component_links' composite FK).

    Returns:
        Dict[str, Any]: Column definitions for the table, keyed by column
        name, plus any of the special ``__``/``_``-prefixed keys the table
        needs (composite indexes, composite/partial-unique constructs).
    """
    if table_type == "sessions":
        return get_session_table_schema(capabilities)
    if table_type == "runs":
        return _get_run_table_schema(capabilities, session_table_name, db_schema)
    if table_type == "evals":
        return get_eval_table_schema(capabilities)
    if table_type == "metrics":
        return get_metrics_table_schema(capabilities)
    if table_type == "memories":
        return get_memory_table_schema(capabilities)
    if table_type == "knowledge":
        return get_knowledge_table_schema(capabilities)
    if table_type == "versions":
        return get_versions_table_schema()
    if table_type == "traces":
        return get_trace_table_schema()
    if table_type == "spans":
        return _get_span_table_schema(capabilities, traces_table_name, db_schema)
    if table_type == "components":
        return get_component_table_schema(capabilities)
    if table_type == "component_configs":
        return get_component_configs_table_schema(capabilities, components_table_name, db_schema)
    if table_type == "component_links":
        return get_component_links_table_schema(
            capabilities, components_table_name, component_configs_table_name, db_schema
        )
    if table_type == "learnings":
        return get_learnings_table_schema(capabilities)
    if table_type == "schedules":
        return get_schedule_table_schema(capabilities)
    if table_type == "schedule_runs":
        return _get_schedule_runs_table_schema(capabilities, schedules_table_name, db_schema)
    if table_type == "jobs":
        return get_jobs_table_schema(capabilities)
    if table_type == "tool_results":
        return get_tool_results_table_schema()
    if table_type == "approvals":
        return get_approval_table_schema(capabilities)
    if table_type == "auth_tokens":
        return get_auth_token_table_schema(capabilities)
    if table_type == "service_accounts":
        return get_service_account_table_schema(capabilities)
    if table_type in MCP_OAUTH_TABLE_SCHEMAS:
        return _widen_mcp_oauth_schema(MCP_OAUTH_TABLE_SCHEMAS[table_type])

    raise ValueError(f"Unknown table type: {table_type}")
