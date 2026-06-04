"""

Run:
    .venvs/demo/bin/python tmp/test_file_gen_os.py

Then open os.agno.com and chat with the agent, e.g.:
    "Generate a DOCX report on Q4 sales trends."
    "Generate a PDF about renewable energy."
    "Generate a CSV of 5 fictional employees."
    "Generate an HTML landing page for a coffee shop."

Files are returned as base64-encoded artifacts in the AgentOS response (see
File._normalise_content in agno/media.py) AND saved to tmp/file_gen_out/.
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
