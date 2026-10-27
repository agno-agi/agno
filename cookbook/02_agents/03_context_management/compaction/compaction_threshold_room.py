"""
Sizing compact_at_tokens
=============================

After a fold, the request still carries the system prompt and tool definitions, the summary,
and the latest turn - compaction never folds the turn the model is answering. If
`compact_at_tokens` is not much bigger than that, a fold lands just under it, the next turn
crosses it again, and every run pays for another summary. Compaction warns when this happens.

Rule of thumb: set `compact_at_tokens` to at least the system prompt and tools, plus the
summary, plus about two of your largest turns. At real thresholds (100k+) this only matters
when single turns are huge - a 60k-token tool result against a 100k threshold, say.

This runs the same conversation twice - six turns of ~700 tokens each - first with a
threshold barely above one turn, then with one sized by the rule of thumb.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

db = SqliteDb(db_file="tmp/compaction_threshold_room.db")


def release_notes(version: int) -> str:
    """Forty changes for one release - about 700 tokens, the same for every version."""
    lines = [f"Release notes for version 2.{version}.0"]
    for change in range(1, 41):
        lines.append(
            f"- change {version}.{change}: ticket OPS-{1000 + 37 * version + change}, rollout {5 + change}%"
        )
    return "\n".join(lines)


def run(label: str, compact_at_tokens: int) -> None:
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        db=db,
        session_id=f"compaction_threshold_room_{uuid4().hex[:8]}",
        add_history_to_context=True,
        compaction=Compaction(
            compact_at_tokens=compact_at_tokens,
            uncompacted_runs=1,
            compacted_token_budget=300,
        ),
    )
    print(f"\n{label}: compact_at_tokens={compact_at_tokens}")
    for version in range(1, 7):
        result = agent.run(
            f"File these release notes. Reply with just: noted.\n\n{release_notes(version)}"
        )
        if result.compaction is not None:
            print(
                f"  run {version}: folded -> {result.compaction.tokens_after} tokens left"
            )
        else:
            print(f"  run {version}: no fold")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # One ~700-token turn plus a 300-token summary is already ~1,000: every run folds, and
    # compaction warns that the threshold leaves no room.
    run("Too small", compact_at_tokens=1_200)
    # The summary plus about two turns, with room to spare: a fold every few runs, no warning.
    run("Sized by the rule of thumb", compact_at_tokens=3_000)
