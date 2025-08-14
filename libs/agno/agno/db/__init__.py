from agno.db.base import BaseDb, SessionType

__all__ = [
<<<<<<< HEAD
    "BaseDb", 
    "SessionType",
]

=======
    "BaseDb",
    "SessionType",
]


>>>>>>> 7e718322026f5ba95c3d959c9c42abfe440776d6
def __getattr__(name: str):
    """Lazy import for database implementations to avoid forcing all dependencies."""
    if name == "DynamoDb":
        from agno.db.dynamo import DynamoDb
<<<<<<< HEAD
        return DynamoDb
    elif name == "MongoDb":
        from agno.db.mongo import MongoDb
        return MongoDb
    elif name == "PostgresDb":
        from agno.db.postgres import PostgresDb
        return PostgresDb
    # Add other db implementations as needed
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
=======

        return DynamoDb
    elif name == "MongoDb":
        from agno.db.mongo import MongoDb

        return MongoDb
    elif name == "PostgresDb":
        from agno.db.postgres import PostgresDb

        return PostgresDb
    # Add other db implementations as needed
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
>>>>>>> 7e718322026f5ba95c3d959c9c42abfe440776d6
