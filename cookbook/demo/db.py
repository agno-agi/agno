# ============================================================================
# Configure database for storing sessions, memories, metrics, evals and knowledge
# ============================================================================

# Used for Knowledge VectorDB
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


class DemoDBType:
    DYNAMODB = "dynamodb"
    MONGO = "mongo"
    MYSQL = "mysql"
    POSTGRES = "postgres"
    ASYNC_POSTGRES = "async_postgres"
    SINGLESTORE = "singlestore"
    SQLITE = "sqlite"
    ASYNC_SQLITE = "async_sqlite"


# --- Adjust the type here to use a different database across the demo folder ---
db_type = DemoDBType.POSTGRES

if db_type == DemoDBType.POSTGRES:
    # Setup Postgres DB for demo
    from agno.db.postgres import PostgresDb

    demo_db = PostgresDb(
        id="agno-demo-db",
        db_url=db_url,
    )

    mcp_db = PostgresDb(
        id="agno-demo-db",  # Same DB id as main demo db, but using different tables for MCP
        db_url=db_url,
        session_table="mcp_sessions",
        memory_table="mcp_memories",
        metrics_table="mcp_metrics",
        eval_table="mcp_evals",
    )

    finance_db = PostgresDb(
        id="agno-finance-db",
        db_url=db_url,
        session_table="finance_sessions",
        memory_table="finance_memories",
        metrics_table="finance_metrics",
        eval_table="finance_evals",
    )

elif db_type == DemoDBType.ASYNC_POSTGRES:
    # Setup Async Postgres DB for demo
    from agno.db.postgres import AsyncPostgresDb

    db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
    demo_db = AsyncPostgresDb(
        id="agno-demo-db",
        db_url=db_url,
    )

    mcp_db = AsyncPostgresDb(
        id="agno-demo-db",  # Same DB id as main demo db, but using different tables for MCP
        db_url=db_url,
        session_table="mcp_sessions",
        memory_table="mcp_memories",
        metrics_table="mcp_metrics",
        eval_table="mcp_evals",
    )

    finance_db = AsyncPostgresDb(
        id="agno-finance-db",
        db_url=db_url,
        session_table="finance_sessions",
        memory_table="finance_memories",
        metrics_table="finance_metrics",
        eval_table="finance_evals",
    )

elif db_type == DemoDBType.DYNAMODB:
    # Setup DynamoDB DB for demo
    from agno.db import DynamoDb

    # Setup the DynamoDB database
    demo_db = DynamoDb(
        id="agno-demo-db",
    )

    mcp_db = DynamoDb(
        id="agno-demo-db",  # Same DB id as main demo db, but using different tables for MCP
        session_table="mcp_sessions",
        memory_table="mcp_memories",
        metrics_table="mcp_metrics",
        eval_table="mcp_evals",
    )

    finance_db = DynamoDb(
        id="agno-finance-db",
        session_table="finance_sessions",
        memory_table="finance_memories",
        metrics_table="finance_metrics",
        eval_table="finance_evals",
    )

elif db_type == DemoDBType.SQLITE:
    # Setup SQLite DB for demo
    from agno.db.sqlite import SqliteDb

    demo_db = SqliteDb(
        id="agno-demo-db",
        db_file="tmp/demo.db",
    )

    mcp_db = SqliteDb(
        id="agno-demo-db",  # Same DB id as main demo db, but using different tables for MCP
        session_table="mcp_sessions",
        memory_table="mcp_memories",
        metrics_table="mcp_metrics",
        eval_table="mcp_evals",
        db_file="tmp/demo.db",
    )

    finance_db = SqliteDb(
        id="agno-finance-db",
        session_table="finance_sessions",
        memory_table="finance_memories",
        metrics_table="finance_metrics",
        eval_table="finance_evals",
        db_file="tmp/finance.db",
    )

elif db_type == DemoDBType.ASYNC_SQLITE:
    # Setup Async SQLite DB for demo
    from agno.db.sqlite import AsyncSqliteDb

    demo_db = AsyncSqliteDb(
        id="agno-demo-db",
        db_file="tmp/demo.db",
    )

    mcp_db = AsyncSqliteDb(
        id="agno-demo-db",  # Same DB id as main demo db, but using different tables for MCP
        session_table="mcp_sessions",
        memory_table="mcp_memories",
        metrics_table="mcp_metrics",
        eval_table="mcp_evals",
        db_file="tmp/demo.db",
    )

    finance_db = AsyncSqliteDb(
        id="agno-finance-db",
        session_table="finance_sessions",
        memory_table="finance_memories",
        metrics_table="finance_metrics",
        eval_table="finance_evals",
        db_file="tmp/finance.db",
    )

elif db_type == DemoDBType.MYSQL:
    # Setup MySQL DB for demo
    from agno.db.mysql import MySQLDb

    demo_db = MySQLDb(
        id="agno-demo-db",
        db_url="mysql+pymysql://ai:ai@localhost:3306/ai",
    )

    mcp_db = MySQLDb(
        id="agno-demo-db",  # Same DB id as main demo db, but using different tables for MCP
        db_url="mysql+pymysql://ai:ai@localhost:3306/ai",
        session_table="mcp_sessions",
        memory_table="mcp_memories",
        metrics_table="mcp_metrics",
        eval_table="mcp_evals",
    )

    finance_db = MySQLDb(
        id="agno-finance-db",
        db_url="mysql+pymysql://ai:ai@localhost:3306/ai",
        session_table="finance_sessions",
        memory_table="finance_memories",
        metrics_table="finance_metrics",
        eval_table="finance_evals",
    )

elif db_type == DemoDBType.SINGLESTORE:
    # Setup SingleStore DB for demo
    from os import getenv

    from agno.db.singlestore import SingleStoreDb

    USERNAME = getenv("SINGLESTORE_USERNAME")
    PASSWORD = getenv("SINGLESTORE_PASSWORD")
    HOST = getenv("SINGLESTORE_HOST")
    PORT = getenv("SINGLESTORE_PORT")
    DATABASE = getenv("SINGLESTORE_DATABASE")

    _db_url = f"mysql+pymysql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}?charset=utf8mb4"
    demo_db = SingleStoreDb(
        id="agno-demo-db",
        db_url=_db_url,
    )

    mcp_db = SingleStoreDb(
        id="agno-demo-db",  # Same DB id as main demo db, but using different tables for MCP
        db_url=_db_url,
        session_table="mcp_sessions",
        memory_table="mcp_memories",
        metrics_table="mcp_metrics",
        eval_table="mcp_evals",
    )

    finance_db = SingleStoreDb(
        id="agno-finance-db",
        db_url=_db_url,
        session_table="finance_sessions",
        memory_table="finance_memories",
        metrics_table="finance_metrics",
        eval_table="finance_evals",
    )

elif db_type == DemoDBType.MONGO:
    from agno.db.mongo import MongoDb

    _db_url = "mongodb://mongoadmin:secret@localhost:27017"
    demo_db = MongoDb(
        id="agno-demo-db",
        db_url=_db_url,
    )

    mcp_db = MongoDb(
        id="agno-demo-db",  # Same DB id as main demo db, but using different tables for MCP
        db_url=_db_url,
        session_collection="mcp_sessions",
        memory_collection="mcp_memories",
        metrics_collection="mcp_metrics",
        eval_collection="mcp_evals",
    )

    finance_db = MongoDb(
        id="agno-finance-db",
        db_url=_db_url,
        session_collection="finance_sessions",
        memory_collection="finance_memories",
        metrics_collection="finance_metrics",
        eval_collection="finance_evals",
    )
