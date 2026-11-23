"""
Strip Reasoning From History
============================

Demonstrates `strip_reasoning_from_history`: earlier runs are replayed to the model as text and
tool calls only, without their reasoning (thinking text, signatures, reasoning items).

Some providers bind replayed reasoning to the exact request it came from. Claude verifies each
signed thinking block against the system prompt and earlier messages, so when the system prompt
changes between runs (here, the current time from `add_datetime_to_context`) a follow-up that
replays the old thinking is rejected with a 400. Stripping the reasoning of earlier runs avoids
that. The current run keeps its reasoning, so tool-use loops still work, and the stored session
keeps everything.

Prefer a system prompt that stays the same across runs when you can: it also keeps prompt
caching effective. Use this setting when it cannot, or to replay history across providers.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Claude(id="claude-haiku-5-5", thinking={"type": "adaptive"}),
    db=SqliteDb(db_file="tmp/strip_reasoning.db"),
    # The time (to the microsecond) makes the system prompt different on every run.
    add_datetime_to_context=True,
    add_history_to_context=True,
    # Replay earlier runs without their thinking blocks.
    strip_reasoning_from_history=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What is 17 * 23? Think it through.", session_id="strip-reasoning-demo"
    )
    agent.print_response("Now multiply that by 3.", session_id="strip-reasoning-demo")

    # The stored session still holds the signed thinking blocks; only the model input drops them.
    session = agent.get_session(session_id="strip-reasoning-demo")
    stored_blocks = [
        block.get("type")
        for run in session.runs
        for m in (run.messages or [])
        if m.role == "assistant" and m.provider_data
        for block in m.provider_data.get("content_blocks", [])
    ]
    print("Thinking blocks kept in storage:", stored_blocks.count("thinking"))
