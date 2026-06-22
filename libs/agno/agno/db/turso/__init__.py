from agno.db.turso.turso import TursoDb

__all__ = ["TursoDb"]


_ASYNC_NOT_SUPPORTED = (
    "AsyncTursoDb is not yet supported. The upstream `sqlalchemy-libsql` package "
    "does not currently expose a working async DBAPI driver — its `aiolibsql` entry "
    "point is a stub over the synchronous driver, so `create_async_engine` raises "
    "`AwaitRequired` at execution time. Use the synchronous `TursoDb` for now; "
    "see https://github.com/agno-agi/agno/issues/7850 for status."
)


def __getattr__(name: str):
    if name == "AsyncTursoDb":
        raise ImportError(_ASYNC_NOT_SUPPORTED)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
