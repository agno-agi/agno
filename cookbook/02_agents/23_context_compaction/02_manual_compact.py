"""
Manual Compaction
=================

`agent.compact()` is the /compact analog: fold everything older than the kept
tail right now, without waiting for a threshold. Operator instructions steer
what the summary keeps in extra detail.

Run: .venvs/demo/bin/python cookbook/02_agents/23_context_compaction/02_manual_compact.py
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

agent = Agent(
    id="manual-compact-demo",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction.db"),
    add_history_to_context=True,
    # A small window keeps the demo's kept tail short, so compact() has
    # something older than the tail to fold even in a brief conversation.
    compaction=Compaction(context_window=2_000),
    markdown=True,
)

session_id = "manual-compact-session"

agent.print_response(
    "We are debugging a flaky login test. It fails roughly 1 in 5 runs with a "
    "TimeoutError in auth_client.py line 142. Note the details.",
    session_id=session_id,
)
agent.print_response(
    "We found the cause: the retry budget is 3 but the mock server needs 4. "
    "The fix is in review as PR 8812.",
    session_id=session_id,
)
agent.print_response(
    "Unrelated: also remind me later that the staging database password rotates on Friday.",
    session_id=session_id,
)

# Fold the conversation so far. The record is persisted on the session; the
# next run builds from the summary plus the recent tail.
record = agent.compact(
    session_id=session_id,
    instructions="Keep every detail about the flaky login test and its fix.",
)

if record is None:
    print("Nothing to fold yet: the whole conversation fits in the kept tail.")
else:
    print(f"Compacted: record {record.id}")
    print(f"  reason: {record.reason}")
    print(f"  summary:\n{record.summary}")

# The agent still knows both threads of the conversation.
agent.print_response(
    "What was the fix for the flaky test, and what did I ask you to remind me about?",
    session_id=session_id,
)
