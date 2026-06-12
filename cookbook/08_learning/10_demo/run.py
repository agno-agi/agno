"""
Learning Demo: AgentOS Server
=============================
Serves the ops assistant on an AgentOS instance, which exposes the
/learnings CRUD endpoints and powers the Learning pages at os.agno.com.

Run seed.py first so the Learning pages have data:
    .venvs/demo/bin/python cookbook/08_learning/10_demo/seed.py

Then start the server:
    .venvs/demo/bin/python cookbook/08_learning/10_demo/run.py

Then open https://os.agno.com, connect to http://localhost:7777, and
browse the Learning section: User Profiles, User Memories, Entity
Memories, Session Context, and Decision Logs.

Interactive API docs are at http://localhost:7777/docs.
"""

from agents import ops_assistant
from agno.os import AgentOS

agent_os = AgentOS(
    description="Learning demo: one agent with every learning store enabled",
    agents=[ops_assistant],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
