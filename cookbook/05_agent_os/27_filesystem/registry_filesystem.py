"""Register filesystems for agents created in Studio.

In Studio's File System section, select personal-notes or handbook under
Or select filesystems. The registry retains backend and tool settings.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(id="studio-db", db_file="tmp/studio_filesystem.db")
model = OpenAIResponses(id="gpt-5.6-luna")
notes = FileSystem(db, namespace="agents/{agent_id}/notes")
handbook = FileSystem(db, namespace="shared/handbook")

registry = Registry(
    models=[model],
    dbs=[db],
    filesystems={
        "personal-notes": notes,
        "handbook": handbook.tools(read_only=True, add_instructions=True),
    },
)

# Stored agent configs use references; the same path is used by Studio.
agent = Agent.from_dict(
    {
        "id": "filesystem-assistant",
        "name": "Filesystem Assistant",
        "model": model.to_dict(),
        "filesystem": [
            {"registry_id": "personal-notes"},
            {"registry_id": "handbook"},
        ],
    },
    registry=registry,
    strict=True,
)

agent_os = AgentOS(id="filesystem-studio", agents=[agent], db=db, registry=registry)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="registry_filesystem:app", reload=True)
