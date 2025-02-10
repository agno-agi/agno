from agno.agent import Agent
from agno.tools.postgres import PostgresTools

# Initialize PostgresTools with connection details
postgres_tools = PostgresTools(
    host="localhost",
    port=5532,
    db_name="ai",
    user="ai",
    password="ai",
    table_schema="ai",
)

# Create an agent with the PostgresTools
agent = Agent(tools=[postgres_tools])

agent.print_response("List the tables in the database", markdown=True)

agent.print_response("""
Please run a SQL query to get all sessions in `agent_sessions` created in the last 24 hours.
""")
