from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.file_generation import FileGenerationTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from agno.db.postgres import PostgresDb
db = PostgresDb(
    session_table="workflow_session",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

file_agent = Agent(
    name="File Output Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    send_media_to_model=False,
    tools=[FileGenerationTools(output_directory="tmp")],
    instructions="Just return the file url as it is don't do anythings.",
)

# Define workflow step
file_generation_step = Step(
    name="File Generation Step",
    agent=file_agent,
)

# Define workflow
file_generation_workflow = Workflow(
    name="file-generation-workflow",
    description="Generate files using file generation tools",
    db=db,
    steps=[file_generation_step],
)

agent_os = AgentOS(
    id="agentos-demo",
    agents=[file_agent],
    workflows=[file_generation_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="file_output:app", reload=True)
