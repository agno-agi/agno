from agno.agent.agent import Agent, get_agent_by_id  # noqa: F401
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


class OutputSchema(BaseModel):
    message: str


def sample_tool():
    return "Hello, world!"


registry = Registry(
    name="Agno Registry",
    description="Registry for Agno",
    tools=[DuckDuckGoTools(), sample_tool],
    models=[OpenAIChat(id="gpt-5-mini")],
    dbs=[db],
    schemas={
        "OutputSchema": OutputSchema,
    },
)

# Uncomment this during your first run to save the agent to the database
# agent = Agent(
#     id="registry-agent",
#     model=OpenAIChat(id="gpt-4o-mini"),
#     db=db,
#     tools=[DuckDuckGoTools(), sample_tool],
#     version="v1",
#     output_schema=OutputSchema,
# )
# agent.save()

agent = get_agent_by_id(db=db, id="registry-agent", registry=registry)

agent.print_response("Call the sample tool")
