"""
Shared Prompt
=============

Demonstrates one published Prompt reused by several Agents and a Team, each
holding its own reference, plus a consumer-owned inline fallback.

Key concepts:
- Instructions accept a Prompt whose content is a string or a list of blocks;
  system_message accepts a Prompt with string content only.
- Each consumer keeps an independent reference. Republishing the Prompt moves
  only the consumers that follow "latest" and only when they are loaded again.
- A fallback belongs to one consumer relationship. It is stored on that
  consumer's link row, never in the shared Prompt.
- Prompt resolution is not model fallback. It decides which text the consumer
  loads; it has nothing to do with which model answers.

Resolution order when a consumer is loaded:
- Strict loading (strict=True) raises when the requested version cannot be
  resolved.
- Lenient loading (the default) first tries the requested version, then the
  current published version, then the consumer's own inline fallback.
- With no usable target and no fallback, loading fails either way; a
  Prompt-backed field is never silently dropped.

Warning: a Prompt placed in Team.system_message completely replaces the
generated Team context, including the member roster and the delegation
instructions. Use it only when that is what you want.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.prompt import Prompt
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/prompts.db", id="prompts-db")

CONSUMER_IDS = ("shared-researcher", "shared-writer", "shared-research-team")

# ---------------------------------------------------------------------------
# Create the Prompts
# ---------------------------------------------------------------------------
# A list-content Prompt shared as instructions, and a string-content Prompt
# for the Team's system message.
house_style = Prompt(id="house-style", content=["Be concise.", "Cite your sources."])
team_system = Prompt(
    id="team-system",
    content="You coordinate a small research team. Reply in plain English.",
)

# ---------------------------------------------------------------------------
# Create the Consumers
# ---------------------------------------------------------------------------
# Two Agents reference the same Prompt with different selectors. The writer
# follows latest and carries its own inline fallback, used only by lenient
# loading when no published text can be resolved. No model is needed to save
# or load them.
researcher = Agent(
    id="shared-researcher",
    name="Researcher",
    instructions=Prompt(id="house-style"),
)
writer = Agent(
    id="shared-writer",
    name="Writer",
    instructions=Prompt(id="house-style", version="latest", fallback=["Be concise."]),
)

# The Team reuses the Prompt for its own instructions and replaces its
# generated system message with the string Prompt (see the warning above).
team = Team(
    id="shared-research-team",
    name="Research Team",
    members=[researcher, writer],
    instructions=Prompt(id="house-style"),
    system_message=Prompt(id="team-system"),
)

# ---------------------------------------------------------------------------
# Run the Shared Prompt Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Publish the Prompts first: a consumer can only be saved against
    # published Prompt versions.
    house_style_version = house_style.save(db=db)
    team_system.save(db=db)
    print(f"Published house-style version {house_style_version}")

    # Saving the Team saves its members and every Prompt reference.
    team.save(db=db)

    # Each consumer stores its own reference; the fallback lives in the link
    # row of the consumer that declared it.
    for consumer_id in CONSUMER_IDS:
        config = db.get_config(consumer_id)
        links = db.get_links(consumer_id, version=config["version"])
        prompt_links = [
            (
                link["link_key"],
                link["child_version"],
                (link.get("meta") or {}).get("fallback"),
            )
            for link in links
            if link["link_kind"] == "prompt"
        ]
        print(
            f"{consumer_id}: reference={config['config']['instructions']} links={prompt_links}"
        )
    print(f"Shared Prompt content: {Prompt.load('house-style', db=db).content}")

    # Strict loading succeeds while the pinned versions are published.
    loaded_team = Team.load("shared-research-team", db=db, strict=True)
    print(f"Team instructions: {loaded_team.instructions}")
    print(f"Team system message: {loaded_team.system_message!r}")

    # Republish the shared Prompt and reload: the pinned consumers keep the
    # text they pinned, the writer follows the new version.
    house_style.content = [
        "Be concise.",
        "Cite your sources.",
        "Prefer primary sources.",
    ]
    house_style.save(db=db)
    for consumer_id in ("shared-researcher", "shared-writer"):
        print(f"{consumer_id} reloaded: {Agent.load(consumer_id, db=db).instructions}")
    print(f"Team reloaded: {Team.load('shared-research-team', db=db).instructions}")
