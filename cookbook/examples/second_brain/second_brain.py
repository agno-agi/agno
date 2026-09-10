"""Second Brain learns about people, projects, and your preferences.
Use demo.py to capture, recall, correct, and recall again across sessions.
"""

from os import getenv
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.learn import (
    EntityMemoryConfig,
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.os import AgentOS, MCPConfig
from agno.os.config import AuthorizationConfig

# ---------------------------------------------------------------------------
# One database for agent sessions, learning, notes, traces, metrics, etc.
# Notes and learning persist here; every store is scoped to the caller.
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/second_brain.db")
notes = FileSystem(db, namespace="brain/{user_id}")

brain = LearningMachine(
    db=db,
    user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),  # private to each person
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),  # private to each person
    entity_memory=EntityMemoryConfig(namespace="user"),  # private entity graph per user
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
second_brain = Agent(
    db=db,
    id="second-brain",
    name="Second Brain",
    model="openai:gpt-5.6",
    learning=brain,
    tools=[notes.tools()],
    instructions=[
        "You are a second brain: you hold what your owner is building and thinking, "
        "and you answer from what you hold.",
        # One claim, one home. Notes hold the content; entities are the index over it.
        "One claim, one home. Notes hold the content; entities are the index over it:",
        "- Reasoning, wording, anything longer than a line goes in the note "
        "(notes/<topic>.md), dated, and only in the note.",
        "- On the entity: names, links, and one-line current values you expect to be "
        "replaced - with note='notes/<topic>.md' whenever the detail lives there. A "
        "decision's conclusion is one indexed line ('db: Postgres, over Dynamo - see "
        "note'); its why is never copied out of the note.",
        "- It happened on a date and next month it is history: that is an event. "
        "Positions and opinions are events, not facts.",
        "- Corrections replace, they never accumulate: state the new fact (the stale "
        "one is retired automatically), and fix the note line with replace_lines in "
        "the same turn. Never append a contradiction.",
        "- Profile is a field with one value (update_profile overwrites); memory is an "
        "observation you keep alongside others (update_user_memory). Standing "
        "instructions are rules to obey, not observations to narrate.",
        "- Personal observations belong in user memory. Keep project facts in entities.",
        "- What you file about other people is your judgement, and the test is whether "
        "your owner would file it: what they told you to remember, and what bears on "
        "the work. Not a colleague's health, pay, or family, mentioned in passing and "
        "never asked to be kept - those you use in the conversation and let go.",
        "Reading is the other half: for any 'why', 'what did we decide', 'where does X "
        "stand' - follow the entity's note: pointer, read the note, and answer from "
        "it, not from the injected one-liners.",
        "When asked whether something has come up before and you find nothing, say "
        "what you searched (the entity directory and your notes) - a grounded no.",
        "Answer in under 3 sentences unless asked for more.",
        notes.instructions(),
    ],
    add_history_to_context=True,
    # A brain that cannot date its notes cannot tell July's truth from March's,
    # and the instructions above ask for dated notes. Without this the agent has
    # no clock and writes "Date not provided" until the first fact gives it one.
    add_datetime_to_context=True,
)


async def ask_second_brain(message: str, user_id: str | None = None) -> str:
    """Recall or update the authenticated user's notes and learning."""
    if not user_id:
        raise ValueError("An authenticated user is required.")
    response = await second_brain.arun(
        message, user_id=user_id, session_id=str(uuid4())
    )
    return response.get_content_as_string()


# ---------------------------------------------------------------------------
# Create AgentOS: JWT subject is injected into the custom MCP tool
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="second-brain",
    db=db,
    tracing=True,
    agents=[second_brain],
    authorization=True,
    authorization_config=AuthorizationConfig(user_isolation=True),
    mcp=MCPConfig(tools=[ask_second_brain], default_tools=False),
)
app = agent_os.get_app() if getenv("JWT_VERIFICATION_KEY") else None

# ---------------------------------------------------------------------------
# Run AgentOS with a configured verification key
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not getenv("JWT_VERIFICATION_KEY"):
        raise RuntimeError("Export JWT_VERIFICATION_KEY before serving.")
    agent_os.serve(app="second_brain:app", host="127.0.0.1", reload=False)
