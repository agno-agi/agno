"""Server-side example for the learnings REST endpoints.

This sets up an AgentOS instance with a learning-enabled agent so that you can
exercise the /learnings CRUD endpoints from a client (see rest_api_learnings.py).

Run with:
    .venvs/demo/bin/python cookbook/05_agent_os/learnings/learnings_with_agentos.py

Then in another terminal, run rest_api_learnings.py to hit the endpoints.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = SqliteDb(id="learnings-os-demo", db_file="tmp/learnings_os_demo.db")

learning = LearningMachine(
    db=db,
    model=OpenAIResponses(id="gpt-5.4"),
    user_profile=True,
    user_memory=True,
    namespace="global",
)

assistant = Agent(
    name="Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=["You are a helpful assistant. Use what you know about the user."],
    db=db,
    learning=learning,
)

agent_os = AgentOS(
    description="AgentOS exposing the /learnings CRUD endpoints",
    agents=[assistant],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run the AgentOS.

    The learnings endpoints will be available at:
      GET    /learnings
      POST   /learnings
      GET    /learnings/{learning_id}
      PATCH  /learnings/{learning_id}
      DELETE /learnings/{learning_id}

    See http://localhost:7777/docs for interactive OpenAPI docs.
    """
    agent_os.serve(app="learnings_with_agentos:app", reload=True)
