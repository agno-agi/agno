# ============================================================================
# Configure database for storing session, memory and knowledge
# ============================================================================

# Setup Postgres DB for demo
from agno.db.postgres import PostgresDb

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
demo_db = PostgresDb(
    id="agno-demo-db",
    db_url=db_url,
)

mcp_db = PostgresDb(
    id="agno-demo-db", # Same DB id as main demo db, but using different tables for MCP
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

# Setup DynamoDB DB for demo
from agno.db import DynamoDb

# Setup the DynamoDB database
# demo_db = DynamoDb(
#     id="agno-demo-db",
# )

# mcp_db = DynamoDb(
#     id="agno-demo-db", # Same DB id as main demo db, but using different tables for MCP
#     session_table="mcp_sessions",
#     memory_table="mcp_memories",
#     metrics_table="mcp_metrics",
#     eval_table="mcp_evals",
# )

# finance_db = DynamoDb(
#     id="agno-finance-db",
#     session_table="finance_sessions",
#     memory_table="finance_memories",
#     metrics_table="finance_metrics",
#     eval_table="finance_evals",
# )