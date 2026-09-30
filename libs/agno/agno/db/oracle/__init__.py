from typing import Any

__all__ = [
    "OracleDb",
    "AsyncOracleDb",
]


def __getattr__(name: str) -> Any:
    # Lazy export, mirroring agno.db.postgres: importing this package must
    # not require the oracle extra unless the caller actually reaches for
    # one of these classes.
    if name == "OracleDb":
        from agno.db.oracle.oracle import OracleDb

        return OracleDb
    if name == "AsyncOracleDb":
        from agno.db.oracle.async_oracle import AsyncOracleDb

        return AsyncOracleDb
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
