"""
SQL Tools Example - Database Agent

This example demonstrates SQLTools with safety features,
statistics, and advanced querying capabilities. The agent can safely
explore databases, analyze data, and export results.

Features demonstrated:
- Read-only mode for safe exploration
- Table sampling and statistics
- Query validation and safety checks
- Smart error handling with helpful tips
- Result export to JSON/CSV

Run: `python cookbook/tools/sql_tools.py`
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.sql import SQLTools

# Example 1: Safe database exploration with read-only mode
print("\n" + "=" * 80)
print("Example 1: Safe Database Exploration (Read-Only Mode)")
print("=" * 80)

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create agent with read-only SQL tools - can only SELECT, cannot modify data
safe_agent = Agent(
    name="Database Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        SQLTools(
            db_url=db_url,
            read_only=True,  # Only SELECT queries allowed
            max_result_rows=100,  # Limit results to prevent memory issues
            query_timeout=30,  # 30 second timeout for queries
            all=True,  # Enable all tools
        )
    ],
    instructions=[
        "You are a database analyst helping users understand their data.",
        "Always explore tables before querying to understand the schema.",
        "Use get_table_sample to see example data before writing complex queries.",
        "Provide insights and summaries, not just raw data.",
    ],
    markdown=True,
)

safe_agent.print_response(
    "List all tables in the database, then pick an interesting one and show me "
    "its schema, statistics, and a few sample rows."
)

# Example 2: Advanced querying with statistics
print("\n" + "=" * 80)
print("Example 2: Data Analysis with Statistics")
print("=" * 80)

safe_agent.print_response(
    "Find the table with the most rows. Show me its statistics including "
    "row count, indexes, and primary keys. Then get a sample of the data."
)

# Example 3: Search and explore
print("\n" + "=" * 80)
print("Example 3: Table Search and Pattern Matching")
print("=" * 80)

safe_agent.print_response(
    "Search for all tables that contain 'user' in their name. "
    "For each matching table, describe its schema."
)

# Example 4: Complex query with safety validation
print("\n" + "=" * 80)
print("Example 4: Complex Query (with safety checks)")
print("=" * 80)

safe_agent.print_response(
    "Write a query to find the top 10 most common values in any text column "
    "you find interesting. Explain what insights we can gain from this data."
)

# Example 5: Attempting unsafe operations (will be blocked)
print("\n" + "=" * 80)
print("Example 5: Safety Features Demo (Blocked Operations)")
print("=" * 80)

safe_agent.print_response(
    "Try to delete all rows from a table and see what happens. "
    "Then try to drop a table. Explain what happened."
)

# Example 6: Admin mode with write access (use cautiously!)
print("\n" + "=" * 80)
print("Example 6: Admin Mode (Write Access - Use with Caution)")
print("=" * 80)

admin_agent = Agent(
    name="Database Admin",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        SQLTools(
            db_url=db_url,
            read_only=False,  # Allow write operations
            max_result_rows=50,
            all=True,
        )
    ],
    instructions=[
        "You are a database administrator with write access.",
        "ALWAYS validate operations with the user before making changes.",
        "Use WHERE clauses in DELETE and UPDATE statements.",
        "Explain what each query will do before executing.",
    ],
    markdown=True,
)

admin_agent.print_response(
    "Explain the difference between read-only and admin mode. "
    "What safety features protect the database?"
)

# Example 7: Export query results
print("\n" + "=" * 80)
print("Example 7: Export Query Results to File")
print("=" * 80)

safe_agent.print_response(
    "Write a query to get interesting statistics from any table, "
    "then export the results to a JSON file. Tell me what you exported."
)

# Example 8: Error handling and helpful tips
print("\n" + "=" * 80)
print("Example 8: Error Handling with Helpful Tips")
print("=" * 80)

safe_agent.print_response(
    "Try to query a table that doesn't exist. "
    "Then try a query with syntax errors. "
    "Show me how the system provides helpful error messages."
)

print("\n" + "=" * 80)
print("Examples completed! SQLTools provides:")
print("  ✓ Read-only mode for safe data exploration")
print("  ✓ Query validation preventing dangerous operations")
print("  ✓ Table sampling, statistics, and search")
print("  ✓ Smart error messages with actionable tips")
print("  ✓ Result export to JSON/CSV")
print("  ✓ Automatic query limits and timeouts")
print("=" * 80)
