"""
Second Brain - Memory You Own, Behind Your Own MCP Server
=========================================================
A private agent that remembers what you are building: durable notes in its own
filesystem, an entity graph over the people and projects around you, and what
it learns about how you work. It is also an MCP server, so your AI apps
(claude, chatgpt, claude code) can read and write the same brain.

The stores split the work:
- Notes (FileSystem) hold the content: decisions with their reasoning, running
  documents, anything longer than a line.
- Entities index the world: people, projects, systems - one-line current
  values, links, and a note pointer to where the detail lives.
- Profile and memory hold the self: who you are and how you like to work.

Identity is pinned (user_id below): sessions do not thread over MCP and an
unauthenticated /mcp call carries no user, so the personal brain names its
owner once and calls that name nobody land on the same brain.

One caveat, measured rather than assumed: /mcp's run_agent takes an optional
user_id, and a host that fills it wins over the pin - that run's profile and
user memory go to whatever it sent. Entities are global, so the world half of
the brain is shared either way. Run /mcp behind auth (the JWT subject then wins
over both) if your client volunteers a user_id.

Running this file serves the AgentOS on http://localhost:7777
MCP Server on http://localhost:7777/mcp
"""

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
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# One database for agent sessions, learning, notes, traces, metrics, etc.
# Shared world, private self: notes live in the same shared namespace as the
# entities they document; profile and memory stay per-user.
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/second_brain.db")
notes = FileSystem(db, namespace="brain")

brain = LearningMachine(
    db=db,
    user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),  # private to each person
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),  # private to each person
    entity_memory=EntityMemoryConfig(namespace="global"),  # shared by the team
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
        "- Confidences stay private: something shared in confidence about the world "
        "goes to user memory, never to a shared entity - and say so when you file one.",
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
    # The personal brain pins identity: every channel, MCP included, lands here.
    user_id="owner",
    add_history_to_context=True,
    # A brain that cannot date its notes cannot tell July's truth from March's,
    # and the instructions above ask for dated notes. Without this the agent has
    # no clock and writes "Date not provided" until the first fact gives it one.
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Create the AgentOS - API on /, MCP on /mcp
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    db=db,
    tracing=True,
    mcp_server=True,
    agents=[second_brain],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="second_brain:app", reload=True)
