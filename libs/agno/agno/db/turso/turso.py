from typing import Any, Dict, Optional

from agno.db.sqlite.sqlite import SqliteDb
from agno.utils.string import generate_id
from agno.utils.turso import create_turso_engine

try:
    from sqlalchemy.engine import Engine
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class TursoDb(SqliteDb):
    """Interface for interacting with a Turso database.

    Turso is a from-scratch, SQLite-compatible database (the engine behind the
    ``pyturso`` driver). This backend reuses all of ``SqliteDb``'s query logic
    and only swaps the SQLAlchemy engine for the ``pyturso`` dialect (see
    ``agno.utils.turso``). The Turso engine implements ``RETURNING`` and
    ``ON CONFLICT`` natively, so the standard upsert paths work unchanged.

    Uses a local Turso database file. The connection is determined by:
        1. Use the ``db_engine``
        2. Use ``db_file`` (a local Turso database file)
        3. Create a new local database in the current directory
    """

    def __init__(
        self,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        session_table: Optional[str] = None,
        culture_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        components_table: Optional[str] = None,
        component_configs_table: Optional[str] = None,
        component_links_table: Optional[str] = None,
        learnings_table: Optional[str] = None,
        schedules_table: Optional[str] = None,
        schedule_runs_table: Optional[str] = None,
        approvals_table: Optional[str] = None,
        auth_tokens_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Args:
            db_file (Optional[str]): Local Turso database file path.
            db_engine (Optional[Engine]): A pre-built SQLAlchemy engine to use.
            session_table (Optional[str]): Name of the table to store Agent, Team and Workflow sessions.
            culture_table (Optional[str]): Name of the table to store cultural notions.
            memory_table (Optional[str]): Name of the table to store user memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge documents data.
            traces_table (Optional[str]): Name of the table to store run traces.
            spans_table (Optional[str]): Name of the table to store span events.
            versions_table (Optional[str]): Name of the table to store schema versions.
            components_table (Optional[str]): Name of the table to store components.
            component_configs_table (Optional[str]): Name of the table to store component configurations.
            component_links_table (Optional[str]): Name of the table to store component links.
            learnings_table (Optional[str]): Name of the table to store learning records.
            schedules_table (Optional[str]): Name of the table to store cron schedules.
            schedule_runs_table (Optional[str]): Name of the table to store schedule run history.
            id (Optional[str]): ID of the database.
        """
        if id is None:
            seed = db_file or (str(db_engine.url) if db_engine else "sqlite+turso:///agno.db")
            id = generate_id(seed)

        # Build the Turso engine, then hand it to SqliteDb via `db_engine` (engine priority #1),
        # so all of SqliteDb's session/table logic is reused as-is.
        if db_engine is None:
            db_engine = create_turso_engine(db_file=db_file)

        super().__init__(
            db_engine=db_engine,
            session_table=session_table,
            culture_table=culture_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
            versions_table=versions_table,
            components_table=components_table,
            component_configs_table=component_configs_table,
            component_links_table=component_links_table,
            learnings_table=learnings_table,
            schedules_table=schedules_table,
            schedule_runs_table=schedule_runs_table,
            approvals_table=approvals_table,
            auth_tokens_table=auth_tokens_table,
            id=id,
        )

        # Retain Turso connection metadata so `to_dict`/`from_dict` round-trips.
        self.db_file = db_file

    # -- Serialization methods --
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "db_file": self.db_file,
                "type": "turso",
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TursoDb":
        return cls(
            db_file=data.get("db_file"),
            session_table=data.get("session_table"),
            culture_table=data.get("culture_table"),
            memory_table=data.get("memory_table"),
            metrics_table=data.get("metrics_table"),
            eval_table=data.get("eval_table"),
            knowledge_table=data.get("knowledge_table"),
            traces_table=data.get("traces_table"),
            spans_table=data.get("spans_table"),
            versions_table=data.get("versions_table"),
            components_table=data.get("components_table"),
            component_configs_table=data.get("component_configs_table"),
            component_links_table=data.get("component_links_table"),
            learnings_table=data.get("learnings_table"),
            schedules_table=data.get("schedules_table"),
            schedule_runs_table=data.get("schedule_runs_table"),
            approvals_table=data.get("approvals_table"),
            id=data.get("id"),
        )
