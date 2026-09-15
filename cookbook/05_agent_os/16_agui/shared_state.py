"""
Synchronize Shared State over AG-UI
===================================

Give an AG-UI agent a recipe-shaped session state, let its
update_session_state tool change it, and watch the interface emit state
snapshots and JSON Patch deltas.

A delta fires each time a completed tool call leaves state different from the
last payload, and because this agent's session_state seeds the session row that
each run merges in, the first delta of a run reports more than that tool call
touched, unless the request already sent all the state the run starts from. The
README's "Shared state on the wire" has the rest of the payload rules.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/shared_state.py
Try: POST state and ask for a tomato soup at http://localhost:7777/shared-state/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create Stateful Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-shared-state-db",
    db_file="tmp/agui_shared_state.db",
)

INITIAL_RECIPE = {
    "recipe": {
        "title": "Untitled recipe",
        "skill_level": "Beginner",
        "cooking_time": "30 min",
        "special_preferences": [],
        "ingredients": [],
        "instructions": [],
    }
}

recipe_agent = Agent(
    id="agui-recipe-agent",
    name="AG-UI Recipe Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    session_state=INITIAL_RECIPE,
    add_session_state_to_context=True,
    enable_agentic_state=True,
    instructions=[
        "Help the user build one recipe in the shared session state.",
        (
            "When the user requests a recipe change, call update_session_state "
            "with the complete updated recipe object under the recipe key."
        ),
        "Use plain ingredient names; do not use icons or emoji.",
        "After updating state, summarize the change in one sentence.",
    ],
)

agent_os = AgentOS(
    id="agui-shared-state-os",
    description="AgentOS emitting AG-UI state snapshots and deltas.",
    agents=[recipe_agent],
    interfaces=[AGUI(agent=recipe_agent, prefix="/shared-state")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Shared-State Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
