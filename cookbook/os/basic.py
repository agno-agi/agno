from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.os.interfaces.whatsapp import Whatsapp
from agno.team import Team
from agno.tools.calculator import CalculatorTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Setup the database
db = PostgresDb(
    db_url=db_url,
    session_table="sessions",
    user_memory_table="user_memory",
)


basic_agent = Agent(
    name="Calculator Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[CalculatorTools(enable_all=True)],
    db=db,
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_messages=True,
    num_history_runs=3,
    add_datetime_to_instructions=True,
    markdown=True,
)
basic_team = Team(
    name="team",
    team_id="1",
    members=[basic_agent],
    db=db,
    show_tool_calls=True,
)

agent_os = AgentOS(
    description="Example app for basic agent with playground capabilities",
    os_id="basic-app",
    agents=[
        basic_agent,
    ],
    teams=[basic_team],
    interfaces=[Whatsapp(agent=basic_agent), Slack(agent=basic_agent)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
