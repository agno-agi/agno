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
)
web_agent = Agent(
    id="web-agent",
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Search the web for the latest news and trends",
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

# print(research_step.to_dict())
# print(content_planning_step.to_dict())

content_creation_workflow = Workflow(
    id="content-creation-workflow",
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    db=PostgresDb(
        session_table="workflow_session",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
    steps=[research_step, content_planning_step],
)

# Save the workflow to the database
workflow_id = content_creation_workflow.save(db=db)

print(f"Workflow saved with ID: {workflow_id}")

# import json
# workflow_dict = content_creation_workflow.to_dict()
# try:
#     json.dumps(workflow_dict)
# except TypeError as e:
#     print(f"Workflow dict not serializable: {e}")
#     for k, v in workflow_dict.items():
#         try:
#             json.dumps({k: v})
#         except TypeError:
#             print(f"  Field '{k}' not serializable: {type(v)}")


# for i, step in enumerate(content_creation_workflow.steps):
#     print(f"Step {i}: type={type(step)}, isinstance(Step)={isinstance(step, Step)}")