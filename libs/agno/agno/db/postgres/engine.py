"""PostgreSQL engines with Agno's connection-pool and JSON defaults."""

from typing import Any, Dict, Union

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agno.db.utils import json_serializer


def _engine_options(**kwargs: Any) -> Dict[str, Any]:
    return {"pool_pre_ping": True, "pool_recycle": 3600, "json_serializer": json_serializer, **kwargs}


def _postgres_url(db_url: Union[str, URL]) -> URL:
    url = make_url(db_url)
    if url.drivername in ("postgres", "postgresql"):
        return url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() != "postgresql":
        raise ValueError("Expected a PostgreSQL URL")
    return url


def create_postgres_engine(db_url: Union[str, URL], **kwargs: Any) -> Engine:
    """Create a synchronous PostgreSQL engine without opening a connection.

    Defaults to pool_pre_ping=True, pool_recycle=3600 and Agno's JSON serializer.
    Keyword arguments are passed to SQLAlchemy and override these defaults;
    use connect_args for driver options such as connection timeouts or TLS.
    Plain postgres:// and postgresql:// URLs select Psycopg 3. Explicit drivers
    and TLS settings are preserved. URL objects accept unescaped credentials.

    Each call creates a new engine. Reuse it with PostgresDb(db_engine=engine),
    PgVector(db=db) and DbFileSystem(db=db) to share one pool. This factory does
    not cache engines or read environment variables.
    """
    return create_engine(_postgres_url(db_url), **_engine_options(**kwargs))


def create_async_postgres_engine(db_url: Union[str, URL], **kwargs: Any) -> AsyncEngine:
    """Create an asynchronous PostgreSQL engine with create_postgres_engine's defaults.

    Like SQLAlchemy's create_async_engine, this is a synchronous factory: no
    await or connection is needed until the engine is used. Pass it to
    AsyncPostgresDb(db_engine=engine). Explicit drivers must support asyncio.
    """
    return create_async_engine(_postgres_url(db_url), **_engine_options(**kwargs))
