"""Ask OS Manager about this source directory and Agno documentation.

Ask: "Read basic_manager.py and explain how this OS is configured."
Then: "Check the Agno docs and explain how to add a knowledge base."
Or: "How does learning work?" The manager can query docs directly for a short
explanation; source inspection is for questions about this application's setup.

Requires OPENAI_API_KEY for conversations. Agno docs access is enabled by default;
if the docs server is unavailable, the manager continues with its other tools.
Source tools can read/search this directory, but cannot edit files or run code.
Set access_docs=False to use source tools without connecting to the documentation server.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_source.py
"""

from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager

agent_os = AgentOS(
    name="Manager source and docs",
    db=SqliteDb(db_file="tmp/manager_source.db"),
    manager=OSManager(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        root=Path(__file__).parent,
    ),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="manager_source:app", reload=True)
