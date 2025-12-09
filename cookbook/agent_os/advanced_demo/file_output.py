from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.file_generation import FileGenerationTools

db = SqliteDb(db_file="tmp/agentos.db")

file_agent = Agent(
    name="File Output Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    send_media_to_model=False,
    tools=[FileGenerationTools(output_directory="tmp")],
    instructions="Just return the file url as it is don't do anythings.",
)

agent_os = AgentOS(
    id="agentos-demo",
    agents=[file_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="file_output:app", reload=True)
