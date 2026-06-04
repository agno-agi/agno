"""File generation with AgentOS.

This example serves an agent that generates files (JSON, CSV, PDF, DOCX, TXT, HTML)
through AgentOS using the FileGenerationTools toolkit.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/file_generation/file_generation_os.py

Then open os.agno.com, connect to the local server, and chat with the agent, e.g.:
    "Generate a DOCX report on Q4 sales trends."
    "Generate a PDF about renewable energy."
    "Generate a CSV of 5 fictional employees."
    "Generate an HTML landing page for a coffee shop."

Generated files are returned as base64-encoded artifacts in the AgentOS response
and saved to tmp/file_gen_out/.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.tools.file_generation import FileGenerationTools

agent_db = SqliteDb(db_file="tmp/file_gen_os.db")

file_agent = Agent(
    name="File Generator",
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    tools=[
        FileGenerationTools(
            all=True,
            output_directory="tmp/file_gen_out",
        )
    ],
    description="You generate files (JSON, CSV, PDF, DOCX, TXT, HTML) on request.",
    instructions=[
        "When asked to create a file, pick the right generator tool for the requested format.",
        "Always provide meaningful content and a descriptive filename.",
        "Briefly explain what was generated.",
    ],
    markdown=True,
    debug_mode=True,
    add_history_to_context=True,
    num_history_runs=3,
)

agent_os = AgentOS(agents=[file_agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="file_generation_os:app", reload=True)
