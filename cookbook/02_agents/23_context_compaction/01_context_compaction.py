"""
Context Compaction
==================

A session that never ends eventually overflows the model's context window.
History windows drop whole runs; compaction keeps the meaning instead.

`compaction=True` keeps model input under the window: when context nears the
limit, old tool results are elided, and if that is not enough the older
conversation is folded into a running summary. The stored transcript is never
touched — the summary and its boundary live in a small record on the session,
and dropping the record undoes everything.

By default the fold runs in the background before the limit is actually hit,
so the conversation never pauses for compaction.

Run: .venvs/demo/bin/python cookbook/02_agents/23_context_compaction/01_context_compaction.py
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.compaction.compaction import get_owner_records
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

agent = Agent(
    id="compaction-demo",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction.db"),
    add_history_to_context=True,
    # True uses the defaults. The detailed form sets the knobs; a small window
    # here makes the demo compact quickly instead of after 170k tokens.
    compaction=Compaction(context_window=8_000),
    markdown=True,
)

# ---------------------------------------------------------------------------
# A long-running conversation: keep asking until the window would overflow.
# ---------------------------------------------------------------------------
session_id = "compaction-demo-session"

topics = [
    "Explain how a B-tree stays balanced, in detail.",
    "Now compare that with an LSM tree, in detail.",
    "How does PostgreSQL use B-trees for its indexes?",
    "What are the write amplification trade-offs between the two?",
    "Summarize when I should pick each for a new database design.",
    "How do covering indexes change the picture?",
]

for topic in topics:
    agent.print_response(topic, session_id=session_id)

# ---------------------------------------------------------------------------
# The record chain: what got folded, and when.
# ---------------------------------------------------------------------------
session = agent.get_session(session_id=session_id)
records = get_owner_records(session.session_data, "compaction-demo")
print(f"\nCompaction records: {len(records)}")
for record in records:
    stats = record.stats
    print(
        f"  {record.id}  reason={record.reason}  "
        f"tokens {stats.get('tokens_before')} -> {stats.get('tokens_after')}"
    )
