"""
Async Token Counting
=============================

In async runs, `token_counter` can be an async function: it is awaited, so a network call never
blocks the event loop. Here it is the model's own count plus a 10% safety margin, so the fold
happens a little before the limit. Without a margin, `use_model_token_count=True` does the same.

Each turn shares a fixed ~700-token document, so the fold lands on the fifth run every time.
"""

import asyncio
from uuid import uuid4

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

model = OpenAIResponses(id="gpt-5.6-luna")


async def count_with_margin(messages, tools):
    exact = await model.acount_tokens(messages, tools)
    print(f"  counted {int(exact * 1.1)} tokens (model's count {exact} + 10%)")
    return int(exact * 1.1)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=model,
    db=SqliteDb(db_file="tmp/compaction_async_token_counter.db"),
    session_id=f"compaction_async_token_counter_{uuid4().hex[:8]}",
    add_history_to_context=True,
    compaction=Compaction(
        # Four ~700-token turns plus the margin cross this; three do not.
        compact_at_tokens=2_800,
        uncompacted_runs=1,
        token_counter=count_with_margin,
    ),
)


def release_notes(version: int) -> str:
    """Forty changes for one release - the same size for every version."""
    lines = [f"Release notes for version 2.{version}.0"]
    for change in range(1, 41):
        lines.append(
            f"- change {version}.{change}: ticket OPS-{1000 + 37 * version + change}, rollout {5 + change}%"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    for version in range(1, 6):
        print(f"\nRun {version}")
        run = await agent.arun(
            f"File these release notes. Reply with just: noted.\n\n{release_notes(version)}"
        )
        if run.compaction is not None:
            print(
                f"  Folded {run.compaction.messages_compacted} messages ({run.compaction.tokens_before} -> {run.compaction.tokens_after} tokens)"
            )


if __name__ == "__main__":
    asyncio.run(main())
