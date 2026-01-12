from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Define agents
hackernews_agent = Agent(
    id="hackernews-agent",
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Extract key insights and content from Hackernews posts",
    db=db,
)
web_agent = Agent(
    id="web-agent",
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Search the web for the latest news and trends",
    db=db,
)

# Define steps
research_step = Step(
    name="Research Step",
    agent=hackernews_agent,
)

content_planning_step = Step(
    name="Content Planning Step",
    agent=web_agent,
)

content_creation_workflow = Workflow(
    id="content-creation-workflow",
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    db=db,
    steps=[research_step, content_planning_step],
)

# Save the workflow to the database
# workflow_id = content_creation_workflow.save(db=db)

content_creation_workflow.print_response(input="AI trends in 2024", markdown=True)
