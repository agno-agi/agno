from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.websearch import WebSearchTools

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

research_agent = Agent(
    name="Research Agent",
    checkpoint="tool-batch",
    id="research_agent",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=["You are a research agent"],
    tools=[WebSearchTools()],
    db=db,
)

agent_os = AgentOS(
    id="checkpointing-demo",
    name="Checkpointing Demo",
    description="A demo of checkpointing in AgentOS",
    agents=[research_agent],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="checkpointing:app", reload=True)
