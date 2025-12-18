from agno.agent.agent import get_agent_by_id
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = get_agent_by_id(db=db, id="agno-agent")

agent.print_response("How many people live in Canada?")
