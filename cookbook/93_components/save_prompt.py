"""
Save a Prompt
=============

Demonstrates creating a reusable text Prompt, publishing it with an explicit
save, loading the current published version, publishing changed content as a
new immutable version, and loading an earlier version unchanged.

Key concepts:
- Prompt.save() always appends a new published version, even when the content
  is identical to the previous one.
- Prompt.load() reads the current published version unless a version is given.
- Storage does not call a model; this example needs no provider credentials.
"""

from agno.db.sqlite import SqliteDb
from agno.prompt import Prompt

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# A local SQLite file keeps the example self-contained. Every run appends new
# versions; nothing is deleted.
db = SqliteDb(db_file="tmp/prompts.db", id="prompts-db")

# ---------------------------------------------------------------------------
# Create the Prompt
# ---------------------------------------------------------------------------
# Content is a string or a list of instruction blocks.
support_prompt = Prompt(
    id="support-guidelines",
    name="Support guidelines",
    description="Shared support behaviour",
    content=["Be concise.", "Never expose private customer data."],
)

# ---------------------------------------------------------------------------
# Run the Prompt Save Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Publish the first version. save() returns the integer version it created.
    first_version = support_prompt.save(db=db)
    print(f"Published version {first_version}")

    # load() without a version reads the current published pointer.
    current = Prompt.load("support-guidelines", db=db)
    print(f"Current content: {current.content}")

    # Change the content and save again: a new immutable version is published
    # and becomes current.
    support_prompt.content = [
        "Be concise.",
        "Never expose private customer data.",
        "Offer a human handoff when the customer asks for one.",
    ]
    second_version = support_prompt.save(db=db)
    print(f"Published version {second_version} with changed content")
    print(f"Current content: {Prompt.load('support-guidelines', db=db).content}")

    # The earlier version is still there and still reads exactly as published.
    earlier = Prompt.load("support-guidelines", db=db, version=first_version)
    print(f"Version {first_version} is unchanged: {earlier.content}")

    # Saving identical content still creates a version: every explicit save is
    # a publication, so the version history is a complete record.
    third_version = support_prompt.save(db=db)
    print(f"Identical content saved again as version {third_version}")
    print(
        f"Current pointer: {db.get_component('support-guidelines')['current_version']}"
    )
