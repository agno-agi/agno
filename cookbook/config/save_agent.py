from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    id="agno-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    name="Agno Agent",
    version="v1",
    db=db,
    tools=[DuckDuckGoTools()],
)

agent.print_response("How many people live in Canada?")

# Save the agent to the database
agent.save()

# By default, upsert is True, so the agent will be updated if it already exists. To prevent this, you can set upsert to False.
# The command below will raise an error if the agent already exists.
# agent.save(upsert=False)

# Update the agent model and version
# agent.model = OpenAIChat(id="gpt-4o")
# agent.version = "v2"
# agent.save()

# Delete the agent from the database.
# By default, delete will delete the current version of the agent. And set the next version as the current version.
agent.delete()

# Delete all versions of the agent
# This will delete all versions of the agent
# agent.delete(all_versions=True)
