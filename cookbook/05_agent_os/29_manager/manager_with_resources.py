"""Serve an AgentOS with an OS manager, a notebook and memory.

Ask it to save a project note or remember how you like answers. Notes are shared
across users; memory is kept per user. Use the same user id across sessions to
try memory. The notebook tools share names with the source file tools, and
AgentOS refuses that combination at startup, so this example sets no root. See
manager_source.py for source access.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_with_resources.py
"""

from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.learn import (
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager

db = SqliteDb(db_file="tmp/manager_resources.db")
model = OpenAIResponses(id="gpt-5.6-luna")

# Everyone using this OS manager shares the notebook.
notes = FileSystem(db, namespace="shared-notes", user_scoped=False)

# The manager remembers each user separately.
memory = LearningMachine(
    name="manager-memory",
    db=db,
    model=model,
    user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
)

agent_os = AgentOS(
    name="Manager with resources",
    db=db,
    manager=OSManager(
        model=model,
        tools=[notes.tools()],
        learning=memory,
        instructions=notes.instructions(),
    ),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="manager_with_resources:app", reload=True)
