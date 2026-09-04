"""
Compaction With A Searchable Archive
=============================

`searchable=True` gives the agent read-only search over its own archived
history, which changes what a summary is for. Normally a summary replaces the
conversation, so any detail it left out is gone. Here the originals are still
stored, so the summary works as an index and the agent can go read the rest.

This example plants a specific fact early, buries it under enough turns to be
compacted away, and then asks for it back.

The flow is summary-first, archive-as-fallback. When a summary is enough the
agent just answers from it. When the question needs an exact value a summary is
unlikely to have kept, the agent reads the archive instead - you will see the
tool call in the output.

Two built-in nudges make that fallback reliable: the summarizer is asked to end
with a "Not covered here:" line naming what it dropped, and the summary message
tells the agent to consult the archive before answering anything that turns on
an exact value.
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
compaction = Compaction(
    compact_at_runs=4,
    # Adds read_file, list_files and search_content, scoped to this session's
    # archive - one session can never read another's history.
    searchable=True,
    # The turns here are short, so keep only one of them: the guard skips a fold
    # that would not be meaningfully larger than the tail it keeps.
    keep_last_runs=1,
)

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    session_id="compaction_searchable",
    add_history_to_context=True,
    num_history_runs=100,
    compaction=compaction,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Plant a fact that the summary is unlikely to preserve verbatim.
    # Values the model cannot guess or reconstruct, so recovering them proves
    # the answer came out of the archive and nowhere else. Deliberately mundane
    # operational data - calling something a "secret" makes some models decline
    # to repeat it, which muddies what the example is demonstrating.
    agent.print_response(
        "Log this for later: the deploy key rotation runbook is ticket "
        "KR-4417-QX, the rotation window is 47 days, and the pinned build "
        "hash is 'b7f2ae91c4'."
    )

    # 2. Bury it under enough unrelated turns to push it past the threshold.
    for question in [
        "What is a blue-green deployment?",
        "How does a canary release differ from that?",
        "What is a good rollback strategy?",
        "How should we monitor a deploy?",
        "What belongs in a post-deploy checklist?",
    ]:
        agent.print_response(question)

    # 3. Ask for the buried fact. It is no longer in context, so the agent has
    #    to find it in the archive. Asking for the build hash makes that
    #    verifiable: a ticket id is guessable from its pattern, a random hash
    #    is not.
    agent.print_response(
        "What exactly was the pinned build hash, and how long is the rotation window? "
        "Answer only from what I told you earlier."
    )

    print(f"\nCompactions: {compaction.stats.compactions}")
