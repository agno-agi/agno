"""
Image Generation Model
======================

Demonstrates image generation model.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(db_file="tmp/persistent_memory.db")
image_agent = Agent(
    id="image_generation_model",
    db=agent_db,
    model=Gemini(
        id="gemini-3-pro-image-preview",
        response_modalities=["Text", "Image"],
    ),
    add_history_to_context=True,
    num_history_runs=3,
)


# Setup our AgentOS app
agent_os = AgentOS(
    agents=[image_agent],
    interfaces=[Whatsapp(agent=image_agent)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="image_generation_model:app", reload=True)
