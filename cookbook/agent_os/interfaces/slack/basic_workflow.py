from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Define agents for the workflow
researcher_agent = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    role="Search the web and gather comprehensive research on the given topic",
    instructions=[
        "Search for the most recent and relevant information",
        "Focus on credible sources and key insights",
        "Summarize findings clearly and concisely",
    ],
)

writer_agent = Agent(
    name="Content Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Create engaging content based on research findings",
    instructions=[
        "Write in a clear, engaging, and professional tone",
        "Structure content with proper headings and bullet points",
        "Include key insights from the research",
        "Keep content informative yet accessible",
    ],
)

# Create workflow steps
research_step = Step(
    name="Research Step",
    agent=researcher_agent,
)

writing_step = Step(
    name="Writing Step",
    agent=writer_agent,
)

# Create the workflow
content_workflow = Workflow(
    name="Content Creation Workflow",
    description="Research and create content on any topic via Slack",
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    steps=[research_step, writing_step],
    session_id="slack_workflow_session",
)

# Create AgentOS with Slack interface for the workflow
agent_os = AgentOS(
    workflows=[content_workflow],
    interfaces=[Slack(workflow=content_workflow)],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic_workflow:app", reload=True)
