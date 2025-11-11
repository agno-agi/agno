"""Example for AgentOS to show how to pass dependencies to an agent."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS

# Setup the database
db = PostgresDb(id="basic-db", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Setup basic agents, teams and workflows
story_writer = Agent(
    id="story-writer-agent",
    name="Story Writer Agent",
    db=db,
    markdown=True,
    instructions="You are a story writer. You are asked to write a story about a robot. Always name the robot {robot_name}",
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example AgentOS to show how to pass dependencies to an agent",
    agents=[story_writer],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    Test passing dependencies to an agent:
    curl --location 'http://localhost:7777/agents/story-writer-agent/runs' \
        --header 'Content-Type: application/x-www-form-urlencoded' \
        --data-urlencode 'message=Write me a 5 line story.' \
        --data-urlencode 'dependencies={"robot_name": "Anna"}'
    """
    agent_os.serve(app="pass_dependencies_to_agent:app", reload=True)
