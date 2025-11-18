"""Use SingleStore as the database for an agent.

Run `pip install ddgs sqlalchemy openai` to install dependencies."""

from urllib.parse import quote_plus

from agno.agent import Agent
from agno.db.singlestore.singlestore import SingleStoreDb
from agno.tools.duckduckgo import DuckDuckGoTools

password = "CYmqkI1V6Z*Y66XykCib=mV{]y"
encoded_password = quote_plus(password)

db_url = f"mysql+pymysql://manu-e79af:{encoded_password}@svc-3482219c-a389-4079-b18b-d50662524e8a-shared-dml.aws-virginia-6.svc.singlestore.com:3333/db_manu_fd070"
db = SingleStoreDb(db_url=db_url)

# Create an agent with SingleStore db
agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    enable_agentic_memory=True,
)
agent.print_response("please remember i like sushi")
