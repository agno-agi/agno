from agno.db.base import BaseDb, SessionType

__all__ = [
    "BaseDb",
    "SessionType",
]


def __getattr__(name: str):
    """Lazy import for database implementations to avoid forcing all dependencies."""
    if name == "DynamoDb":
        from agno.db.dynamo import DynamoDb

        return DynamoDb
    elif name == "MongoDb":
        from agno.db.mongo import MongoDb

        return MongoDb
    elif name == "PostgresDb":
        from agno.db.postgres import PostgresDb

        return PostgresDb
    elif name == "ClickhouseDb":
        from agno.db.clickhouse import ClickhouseDb

        return ClickhouseDb
    elif name == "AsyncClickhouseDb":
        from agno.db.clickhouse import AsyncClickhouseDb

        return AsyncClickhouseDb
    # Add other db implementations as needed
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
