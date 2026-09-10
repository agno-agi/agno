"""AgentOS with an explicit filesystem namespace and storage limits.

Set OPENAI_API_KEY, then run this file.
Ask: Save three product decisions to decisions/product.md.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = SqliteDb(id="custom-namespace-db", db_file="tmp/custom_namespace.db")
filesystem = FileSystem(
    db=db,
    namespace="projects/product-research",
    max_file_bytes=256 * 1024,
    max_namespace_bytes=8 * 1024 * 1024,
)

agent = Agent(
    id="product-researcher",
    name="Product Researcher",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=filesystem,
    instructions="Keep product decisions in your filesystem. Save notes only when asked.",
    markdown=True,
)

# Explicit filesystem configuration keeps its namespace instead of deriving one
# from the agent id. Access is shared by callers allowed to use this agent.
agent_os = AgentOS(
    id="custom-namespace-os",
    db=db,
    agents=[agent],
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777)
