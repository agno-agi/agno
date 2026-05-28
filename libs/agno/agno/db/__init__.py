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
    # Add other db implementations as needed
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
