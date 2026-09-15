"""Oracle engines with Agno's connection-pool and JSON defaults."""

from typing import Any, Dict, Union

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agno.db.utils import json_serializer


def _engine_options(**kwargs: Any) -> Dict[str, Any]:
    # pool_pre_ping=True matters more here than on Postgres: Oracle connections
    # are frequently dropped by a firewall or load balancer's idle timeout, and
    # a dead connection surfaces as an opaque driver error without it.
    return {"pool_pre_ping": True, "pool_recycle": 3600, "json_serializer": json_serializer, **kwargs}


def _oracle_url(db_url: Union[str, URL]) -> URL:
    url = make_url(db_url)
    if url.drivername == "oracle":
        return url.set(drivername="oracle+oracledb")
    if url.get_backend_name() != "oracle":
        raise ValueError("Expected an Oracle URL")
    return url


def create_oracle_engine(db_url: Union[str, URL], **kwargs: Any) -> Engine:
    """Create a synchronous Oracle engine without opening a connection.

    Defaults to pool_pre_ping=True, pool_recycle=3600 and Agno's JSON
    serializer. Keyword arguments are passed to SQLAlchemy and override these
    defaults; use connect_args for driver options such as connection timeouts.
    A plain oracle:// URL selects the python-oracledb dialect. Explicit
    drivers are preserved. URL objects accept unescaped credentials.

    Each call creates a new engine. Reuse it with OracleDb(db_engine=engine)
    and OracleVector(db=db) to share one pool. This factory does not cache
    engines or read environment variables.
    """
    return create_engine(_oracle_url(db_url), **_engine_options(**kwargs))


def create_async_oracle_engine(db_url: Union[str, URL], **kwargs: Any) -> AsyncEngine:
    """Create an asynchronous Oracle engine with create_oracle_engine's defaults.

    Like SQLAlchemy's create_async_engine, this is a synchronous factory: no
    await or connection is needed until the engine is used. Pass it to
    AsyncOracleDb(db_engine=engine). The URL must select the oracledb_async
    dialect (``oracle+oracledb_async://``); the asyncio support in
    python-oracledb only works in thin mode, so this factory never triggers
    the thick client.
    """
    url = make_url(db_url)
    if url.drivername != "oracle+oracledb_async":
        raise ValueError(
            "AsyncOracleDb requires an 'oracle+oracledb_async://' URL so the driver's "
            f"asyncio (thin-mode-only) path is used. Got: {url.drivername}://"
        )
    return create_async_engine(url, **_engine_options(**kwargs))
