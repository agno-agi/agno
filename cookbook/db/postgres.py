from agno.db.postgres.postgres import PostgresDb

db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"

db = PostgresDb(db_url=db_url, agent_session_table="agent_sessions")

# agent = Agent()
# agent.print_response("Hello")
