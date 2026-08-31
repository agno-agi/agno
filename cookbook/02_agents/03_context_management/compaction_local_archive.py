"""
Compaction With A Local Archive
=============================

By default the archive lives in the agent's database, as rows in AgentFS's
generic file table. That is what you want in production: the archive travels
with the session and survives a restart that would orphan a temp directory.

Passing a `LocalFileSystem` writes real markdown files to disk instead, which is
useful while developing - you can open, grep and diff the archive with ordinary
tools. Each session gets its own directory under the root.
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
compaction = Compaction(
    compact_at_runs=3,
    keep_last_runs=1,
    fs=LocalFileSystem(root="tmp/compaction_archive"),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction_local.db"),
    session_id="compaction_local",
    add_history_to_context=True,
    num_history_runs=100,
    compaction=compaction,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for question in [
        "What is idempotency in an HTTP API?",
        "Which methods are idempotent?",
        "How do idempotency keys help with retries?",
        "What should the server store for one?",
    ]:
        agent.print_response(question)

    print(
        "\nArchive written under tmp/compaction_archive - open the .md files to read it."
    )
