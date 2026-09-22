"""
Prompt Version Selection
========================

Demonstrates the three ways a saved Agent can select a Prompt version:
- version omitted: pin the current published version when the Agent is saved
- version=<integer>: pin exactly that published version
- version="latest": follow the current published version each time the Agent
  is loaded

Key concepts:
- Omitted does not mean floating. The pin is resolved once, at save time, and
  written into the saved reference and its link row.
- A loaded object keeps the text it resolved at load time. Publishing a new
  Prompt version changes what the next load sees, not what an already loaded
  object uses between runs.
- Publishing a Prompt and running a model are different operations. This
  example only publishes and loads; no model is called.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.prompt import Prompt

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/prompts.db", id="prompts-db")

AGENT_IDS = ("pinned-at-save", "pinned-explicitly", "follows-latest")

# ---------------------------------------------------------------------------
# Create the Prompt
# ---------------------------------------------------------------------------
greeting = Prompt(id="greeting", content="Greet the user warmly.")

# ---------------------------------------------------------------------------
# Run the Version Selection Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Publish the Prompt the three Agents will reference.
    published = greeting.save(db=db)
    print(f"Published greeting version {published}")

    # Three consumers, three selectors. The Agents need no model to be saved.
    Agent(
        id="pinned-at-save",
        name="Pinned at save",
        instructions=Prompt(id="greeting"),
    ).save(db=db)
    Agent(
        id="pinned-explicitly",
        name="Pinned explicitly",
        instructions=Prompt(id="greeting", version=published),
    ).save(db=db)
    Agent(
        id="follows-latest",
        name="Follows latest",
        instructions=Prompt(id="greeting", version="latest"),
    ).save(db=db)

    # What was actually saved: the config reference and the link row.
    # An omitted selector is stored as the integer it resolved to; "latest" is
    # stored as "latest" with no pinned link version.
    for agent_id in AGENT_IDS:
        config = db.get_config(agent_id)
        prompt_links = [
            link["child_version"]
            for link in db.get_links(agent_id, version=config["version"])
            if link["link_kind"] == "prompt"
        ]
        print(
            f"{agent_id}: reference={config['config']['instructions']} link_version={prompt_links}"
        )

    # Load the floating consumer now, before a new version exists.
    loaded_before = Agent.load("follows-latest", db=db)
    print(f"follows-latest loaded now: {loaded_before.instructions!r}")

    # Publish a new version of the Prompt.
    greeting.content = "Greet the user warmly and ask how you can help."
    newer = greeting.save(db=db)
    print(f"Published greeting version {newer}")

    # The object loaded earlier still holds the text it resolved at load time.
    print(f"Same loaded object after publishing: {loaded_before.instructions!r}")

    # Reloading resolves again: the two pins stay fixed, latest moves.
    for agent_id in AGENT_IDS:
        reloaded = Agent.load(agent_id, db=db)
        print(f"{agent_id} reloaded: {reloaded.instructions!r}")
