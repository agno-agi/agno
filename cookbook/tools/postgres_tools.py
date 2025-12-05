from agno.agent import Agent
from agno.tools.postgres import PostgresTools

# Example 1: Include specific Postgres functions (default behavior - all functions included)
agent = Agent(
    tools=[
        PostgresTools(
            host="localhost",
            port=5532,
            db_name="ai",
            user="ai",
            password="ai",
            table_schema="ai",
        )
    ]
)

# Example 2: Include only read-only operations
agent_readonly = Agent(
    tools=[
        PostgresTools(
            host="localhost",
            port=5532,
            db_name="ai",
            user="ai",
            password="ai",
            table_schema="ai",
            include_tools=[
                "show_tables",
                "describe_table",
                "summarize_table",
                "inspect_query",
            ],
        )
    ]
)

# Example 3: Exclude dangerous operations
agent_safe = Agent(
    tools=[
        PostgresTools(
            host="localhost",
            port=5532,
            db_name="ai",
            user="ai",
            password="ai",
            table_schema="ai",
            exclude_tools=["run_query"],  # Exclude direct query execution
        )
    ]
)

agent.print_response(
    "List the tables in the database and summarize one of the tables", markdown=True
)

agent.print_response("""
Please run a SQL query to get all sessions in `agno_sessions` created in the last 24 hours and summarize the table.
""")
