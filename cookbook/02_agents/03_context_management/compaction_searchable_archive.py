"""
Compaction With A Searchable Archive
=============================

`searchable=True` gives the agent read-only search over its own archived
history, which changes what a summary is for. Normally a summary replaces the
conversation, so any detail it left out is gone. Here the originals are still
stored, so the summary works as an index and the agent can go read the rest.

This example plants a specific fact early, buries it under enough turns to be
compacted away, and then asks for it back.

To make the archive lookup visible, the summarizer here is deliberately told to
write a terse summary that drops identifiers. That forces the agent to call
`search_content` - you will see the tool call in the output. With the default
prompt the summary usually preserves an identifier like this one, the agent
answers straight from it, and no tool call happens at all. Both outcomes are
correct; the archive is the backstop for what a summary did not keep.
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
compaction = Compaction(
    compact_at_runs=4,
    keep_last_runs=2,
    # Adds read_file, list_files and search_content, scoped to this session's
    # archive - one session can never read another's history.
    searchable=True,
    # Deliberately lossy, so the fact survives ONLY in the archive and the
    # lookup is visible. Remove this to get the default (identifier-preserving)
    # summary.
    instructions=(
        "Summarize the conversation in at most 40 words. "
        "Describe topics only - omit every ticket number, identifier and figure."
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction_searchable.db"),
    session_id="compaction_searchable",
    add_history_to_context=True,
    num_history_runs=100,
    compaction=compaction,
    instructions=[
        "If a question refers to something earlier in the conversation that you "
        "cannot see, search your archived history before saying you do not know.",
    ],
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
