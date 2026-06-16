"""
Slack HITL — Required Approval
==============================

Infrastructure agent that handles database schema migrations. Migrations
require admin approval via os.agno.com — the `@approval` decorator creates
a DB record so approvals persist across restarts and leave an audit trail.

Try in Slack:
  @bot migrate users table: add verified_at timestamp column

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from typing import Any, Dict

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool

# Mock schema registry

_TABLES: Dict[str, Dict[str, Any]] = {
    "users": {
        "columns": ["id", "email", "created_at", "updated_at"],
        "rows": 2_500_000,
        "indexes": ["users_pkey", "users_email_idx"],
    },
    "orders": {
        "columns": ["id", "user_id", "status", "total", "created_at"],
        "rows": 8_200_000,
        "indexes": ["orders_pkey", "orders_user_id_idx", "orders_status_idx"],
    },
    "sessions": {
        "columns": ["id", "user_id", "token", "expires_at"],
        "rows": 450_000,
        "indexes": ["sessions_pkey", "sessions_token_idx"],
    },
}

_MIGRATION_LOG: list[Dict[str, str]] = []


@tool
def describe_table(table_name: str) -> str:
    """Get current schema for a table: columns, row count, indexes.

    Args:
        table_name: Table to describe (e.g. "users").
    """
    table = _TABLES.get(table_name)
    if not table:
        return f"Table {table_name!r} not found. Available: {', '.join(_TABLES)}."
    return (
        f"Table: {table_name}\n"
        f"Columns: {', '.join(table['columns'])}\n"
        f"Rows: {table['rows']:,}\n"
        f"Indexes: {', '.join(table['indexes'])}"
    )


@tool
def list_tables() -> str:
    """List all tables in the database with row counts."""
    lines = [f"  {name}: {info['rows']:,} rows" for name, info in _TABLES.items()]
    return "Tables:\n" + "\n".join(lines)


@tool
def list_recent_migrations() -> str:
    """Show recently applied migrations from this session."""
    if not _MIGRATION_LOG:
        return "No migrations applied yet."
    return "\n".join(f"  {m['id']}: {m['description']}" for m in _MIGRATION_LOG[-5:])


# approval_type="required": creates DB record, blocks until resolved
@approval
@tool(requires_confirmation=True)
def add_column(
    table_name: str, column_name: str, column_type: str, nullable: bool = True
) -> str:
    """Add a new column to a table. Requires admin approval.

    High-risk: locks table briefly, may cause replication lag on large tables.

    Args:
        table_name: Target table.
        column_name: New column name.
        column_type: SQL type (e.g. "TEXT", "TIMESTAMP", "INTEGER").
        nullable: Whether column allows NULL (default True).
    """
    table = _TABLES.get(table_name)
    if not table:
        return f"Table {table_name!r} not found."
    if column_name in table["columns"]:
        return f"Column {column_name!r} already exists in {table_name}."

    table["columns"].append(column_name)
    migration_id = f"M{len(_MIGRATION_LOG) + 1:04d}"
    _MIGRATION_LOG.append(
        {"id": migration_id, "description": f"ADD COLUMN {table_name}.{column_name}"}
    )

    null_str = "NULL" if nullable else "NOT NULL"
    return f"Migration {migration_id} applied: ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} {null_str}"


# Another high-risk DDL operation with required approval
@approval
@tool(requires_confirmation=True)
def create_index(table_name: str, column_name: str, unique: bool = False) -> str:
    """Create an index on a column. Requires admin approval.

    High-risk: can lock table for minutes on large tables without CONCURRENTLY.

    Args:
        table_name: Target table.
        column_name: Column to index.
        unique: Whether to create a unique index.
    """
    table = _TABLES.get(table_name)
    if not table:
        return f"Table {table_name!r} not found."
    if column_name not in table["columns"]:
        return f"Column {column_name!r} not in {table_name}. Columns: {', '.join(table['columns'])}."

    index_name = f"{table_name}_{column_name}_idx"
    if index_name in table["indexes"]:
        return f"Index {index_name} already exists."

    table["indexes"].append(index_name)
    migration_id = f"M{len(_MIGRATION_LOG) + 1:04d}"
    unique_str = "UNIQUE " if unique else ""
    _MIGRATION_LOG.append(
        {"id": migration_id, "description": f"CREATE {unique_str}INDEX {index_name}"}
    )

    return f"Migration {migration_id} applied: CREATE {unique_str}INDEX CONCURRENTLY {index_name} ON {table_name}({column_name})"


db = SqliteDb(
    db_file="tmp/hitl_required_approval.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Schema Migration Agent",
    id="schema-migration-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[
        describe_table,
        list_tables,
        list_recent_migrations,
        add_column,
        create_index,
    ],
    instructions=[
        "You are a database migration assistant for a production PostgreSQL cluster.",
        "When asked to modify schema:",
        "1. Use describe_table to understand current state",
        "2. Propose the migration with add_column or create_index",
        "3. Tools with @approval require admin sign-off before execution",
        "4. Report the migration ID after completion",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — required approval demo (DB-backed approval records)",
    agents=[agent],
    db=db,
    interfaces=[
        Slack(
            agent=agent,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_required_approval:app", reload=True)
