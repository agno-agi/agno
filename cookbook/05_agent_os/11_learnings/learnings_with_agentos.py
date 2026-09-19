"""
Serve Agent Learning with AgentOS
=================================

Serve a learning-enabled agent and the shared database that backs both its
automatic user learning and the AgentOS /learnings CRUD routes.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/11_learnings/learnings_with_agentos.py
Try: Run rest_api_learnings.py from this folder in another terminal
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Learning-Enabled AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="learnings-db",
    db_file="tmp/learnings.db",
)

learning = LearningMachine(
    db=db,
    model=OpenAIResponses(id="gpt-5.5"),
    user_profile=True,
    user_memory=True,
    namespace="global",
)

learning_assistant = Agent(
    id="learning-assistant",
    name="Learning Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=learning,
    instructions=(
        "Be concise and helpful. Use persistent user details when they are "
        "relevant to the response."
    ),
)

agent_os = AgentOS(
    id="learnings-os",
    description="AgentOS exposing agent learning and learning CRUD routes.",
    db=db,
    agents=[learning_assistant],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Learnings Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
