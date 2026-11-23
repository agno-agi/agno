"""
inspeximus Integration
======================

Demonstrates memory that stays corrected: a later write to the same key retires the earlier value.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from inspeximus import Inspeximus

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Start from an empty store so the example is repeatable. Re-running it against the
# store it left behind would restate a value that revert() had already retired, and
# inspeximus refuses that on purpose: an echo does not un-retire a correction.
if os.path.exists("agno_memory.json"):
    os.remove("agno_memory.json")

memory = Inspeximus("agno_memory.json")

# A key is what makes the second write RETIRE the first, with no model call and no
# similarity threshold. Without a key, a write is an ordinary appended fact.
memory.remember("The staging database is db-3.internal", key="staging-db")
# ... and the correction, under the same key.
memory.remember("The staging database is db-7.internal", key="staging-db")

# Only the correction comes back. The retired value stays in the history, and recall
# does not hand it to the agent.
current = [hit["text"] for hit in memory.recall("staging database", k=3)]


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(),
    instructions=["Answer from the remembered facts you are given."],
    dependencies={"memory": "\n".join(current)},
    add_dependencies_to_context=True,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    assert current == ["The staging database is db-7.internal"], current
    agent.print_response("Which staging database should I use?")

    # A correction is reversible: revert(key) makes the previous value current again,
    # without naming it, and the agent sees the change on the next turn.
    memory.revert("staging-db")
    restored = [hit["text"] for hit in memory.recall("staging database", k=3)]
    assert restored == ["The staging database is db-3.internal"], restored

    agent.dependencies = {"memory": "\n".join(restored)}
    agent.print_response("Which staging database should I use?")
