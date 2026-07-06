from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from agno.db.sqlite.sqlite import SqliteDb
from agno.utils.string import generate_id

try:
    from sqlalchemy.engine import Engine, create_engine
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

try:
    import sqlalchemy_libsql  # noqa: F401
except ImportError:
    raise ImportError(
        "`sqlalchemy-libsql` not installed. Install with `pip install sqlalchemy-libsql` "
        "(or `pip install agno[turso]`)."
    )


class TursoDb(SqliteDb):
    """Interface for interacting with a Turso / libSQL database.

    Supported modes (in priority order):
        1. db_engine: Use the provided SQLAlchemy Engine as-is.
        2. Embedded replica: db_file + sync_url (+ auth_token). Local file is kept
           in sync with a remote Turso database via libSQL's replica protocol.
        3. Remote-only: url (+ auth_token). All reads/writes go to the hosted DB.
        4. Local libSQL file: db_file only. No replication, just a local libSQL file.
        5. In-memory: none of the above. `sqlite+libsql://` ephemeral DB.

    Args:
        url: Turso/libSQL database URL. Accepts `libsql://host`, `https://host`,
            `wss://host`, or a bare hostname. Used in remote-only mode.
        auth_token: Turso auth token. Required for hosted Turso DBs and embedded replicas.
        sync_url: Remote URL for embedded replicas. When set together with `db_file`,
            the local file is synced from this remote.
        db_file: Local libSQL file path. Used for embedded replicas or local-only mode.
        db_engine: Pre-built SQLAlchemy Engine; bypasses URL/file/replica handling.
        **kwargs: Forwarded to `SqliteDb` (table names, id, etc.).
    """

    def __init__(
        self,
        url: Optional[str] = None,
        auth_token: Optional[str] = None,
        sync_url: Optional[str] = None,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        id: Optional[str] = None,
        **kwargs: Any,
    ):
        if id is None:
            seed = str(db_engine.url) if db_engine is not None else (sync_url or url or db_file or "sqlite+libsql://")
            id = generate_id(seed)

        self.turso_url: Optional[str] = url
        self.turso_sync_url: Optional[str] = sync_url

        engine = db_engine
        resolved_db_url: Optional[str] = None

        if engine is None:
            if sync_url is not None:
                if db_file is None:
                    raise ValueError("`db_file` is required when `sync_url` is provided (embedded replica mode).")
                _ensure_parent_dir(db_file)
                connect_args: Dict[str, Any] = {"sync_url": _normalize_remote_url(sync_url)}
                if auth_token is not None:
                    connect_args["auth_token"] = auth_token
                engine = create_engine(f"sqlite+libsql:///{db_file}", connect_args=connect_args)
            elif url is not None:
                host = _extract_host(url)
                connect_args = {}
                if auth_token is not None:
                    connect_args["auth_token"] = auth_token
                engine = create_engine(
                    f"sqlite+libsql://{host}/?secure=true",
                    connect_args=connect_args,
                )
            elif db_file is not None:
                _ensure_parent_dir(db_file)
                resolved_db_url = f"sqlite+libsql:///{db_file}"
            else:
                resolved_db_url = "sqlite+libsql://"

        super().__init__(
            db_engine=engine,
            db_url=resolved_db_url,
            id=id,
            **kwargs,
        )

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "type": "turso",
                "turso_url": self.turso_url,
                "turso_sync_url": self.turso_sync_url,
            }
        )
        base.pop("db_url", None)
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TursoDb":
        return cls(
            url=data.get("turso_url"),
            sync_url=data.get("turso_sync_url"),
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


def _ensure_parent_dir(db_file: str) -> None:
    Path(db_file).resolve().parent.mkdir(parents=True, exist_ok=True)


def _extract_host(url: str) -> str:
    """Extract the hostname (with optional port/path) from a user-provided URL."""
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    if not host:
        raise ValueError(f"Could not parse a hostname from `{url}`.")
    return f"{host}{parsed.path if parsed.netloc else ''}"


def _normalize_remote_url(url: str) -> str:
    """Normalize a user-provided Turso URL to `libsql://host[:port][/path]`."""
    return f"libsql://{_extract_host(url)}"
