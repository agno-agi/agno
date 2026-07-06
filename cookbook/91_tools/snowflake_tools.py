"""
Snowflake Tools
=============================

Demonstrates Snowflake data warehouse tools for querying data,
exploring schemas, and managing warehouse objects.

Prerequisites:
    1. Install: ``pip install snowflake-connector-python``
    2. Set environment variables:
       ```
       export SNOWFLAKE_ACCOUNT=xy12345.us-east-1
       export SNOWFLAKE_USER=my_user
       export SNOWFLAKE_PASSWORD=my_password
       export SNOWFLAKE_WAREHOUSE=COMPUTE_WH       # optional
       export SNOWFLAKE_DATABASE=MY_DB              # optional
       export SNOWFLAKE_SCHEMA=PUBLIC               # optional
       export SNOWFLAKE_ROLE=ANALYST                # optional
       ```

    For key pair auth, set SNOWFLAKE_PRIVATE_KEY_PATH instead of SNOWFLAKE_PASSWORD:
       ```
       export SNOWFLAKE_PRIVATE_KEY_PATH=/path/to/rsa_key.p8
       ```
       Requires: ``pip install cryptography``
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.snowflake import SnowflakeTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Read-only data analyst agent (default)
analyst_agent = Agent(
    name="Snowflake Analyst",
    model=OpenAIChat(id="gpt-4o"),
    tools=[SnowflakeTools()],
    description="You are a data analyst that can explore and query a Snowflake data warehouse.",
    instructions=[
        "Use get_current_context first to see which warehouse, database, and schema are active.",
        "Use list_databases, list_schemas, and list_tables to explore the warehouse before querying.",
        "Use describe_table to understand column types before writing SQL.",
        "Always use LIMIT in queries to avoid returning too many rows.",
    ],
    markdown=True,
)

# Example 2: Full access agent with DDL and query history
admin_agent = Agent(
    name="Snowflake Admin",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SnowflakeTools(
            enable_get_query_history=True,
            enable_execute_ddl=True,
            enable_insert_record=True,
            enable_update_records=True,
            enable_delete_records=True,
            enable_call_procedure=True,
        )
    ],
    description="You are a Snowflake admin with full read, write, and DDL capabilities.",
    instructions=[
        "Confirm with the user before executing any DDL or delete statements.",
        "Use describe_table to check column names before inserting or updating records.",
        "Use query history to help debug slow queries.",
    ],
    markdown=True,
)

# Example 3: Minimal agent with only query access
query_agent = Agent(
    name="Snowflake Query Runner",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SnowflakeTools(
            enable_query=True,
            enable_list_databases=False,
            enable_list_schemas=False,
            enable_list_tables=False,
            enable_describe_table=False,
            enable_get_current_context=False,
        )
    ],
    description="You are a focused query runner. Execute SQL queries provided by the user.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Check current context
    analyst_agent.print_response(
        "What warehouse, database, and schema am I connected to?",
        stream=True,
    )

    # Explore the warehouse
    analyst_agent.print_response(
        "List all databases in this Snowflake account",
        stream=True,
    )

    # Explore schemas
    analyst_agent.print_response(
        "What schemas are available in the default database?",
        stream=True,
    )

    # Describe a table
    analyst_agent.print_response(
        "Describe the columns in the CUSTOMERS table",
        stream=True,
    )

    # Query data
    analyst_agent.print_response(
        "Find the top 10 customers by total order amount",
        stream=True,
    )
