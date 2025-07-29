from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.postgres import PostgresStorage
from agno.workflow.v2.step import Step
from agno.workflow.v2.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

storage = PostgresStorage(
    db_url=db_url,
    table_name="workflow_v11",
    mode="workflow_v2",
)

web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Search the web for the latest news and trends",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)

# Define steps
research_step = Step(
    name="Research Step",
    agent=web_agent,
)

content_planning_step = Step(
    name="Content Planning Step",
    agent=content_planner,
)

content_creation_workflow = Workflow(
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    storage=storage,
    steps=[research_step, content_planning_step],
)

# Create and use workflow
if __name__ == "__main__":
    content_creation_workflow.print_response(
        message="AI trends in 2024",
        markdown=True,
    )
