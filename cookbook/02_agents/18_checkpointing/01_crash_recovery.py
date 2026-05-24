"""Crash Recovery with checkpoint="steps".

Without checkpointing, an agent run only persists at terminal states. If the
worker dies mid-run, the work is gone — the session row exists, but this
``run_id`` is never recorded under it.

``checkpoint="steps"`` writes after each tool batch (post-gather barrier).
For a run with K tool batches and a final no-tool turn, the DB sees K + 1
writes. If the process crashes between the J-th and (J+1)-th turn, the row
contains everything through turn J; ``/continue`` resumes from there.

This example doesn't actually crash a process — instead, it:
1. Runs an agent with ``checkpoint="steps"`` through a multi-tool task.
2. Prints the checkpoint state from the persisted RunOutput.
3. Demonstrates ``acontinue_run`` against the same run_id — the unified
   ``/continue`` accepts any persisted run (no PAUSED gate).
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses


def search(query: str) -> str:
    """Mock search tool — returns a fixed list of results."""
    return f"Top 3 results for '{query}': result-a, result-b, result-c"


def fetch_detail(item: str) -> str:
    """Mock detail-fetch tool."""
    return f"Detail for {item}: lorem ipsum dolor sit amet"


async def main() -> None:
    agent = Agent(
        name="research-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(
            session_table="checkpoint_demo",
            db_file="tmp/checkpoint_crash_recovery.db",
        ),
        checkpoint="steps",  # write after each tool batch
        tools=[search, fetch_detail],
        instructions=(
            "Use the search tool to find results, then call fetch_detail on each "
            "result you found. Summarize what you learned at the end."
        ),
    )

    response = await agent.arun(input="Research the topic 'agno checkpointing'.")

    print("Initial run completed")
    print("  run_id:", response.run_id)
    print("  session_id:", response.session_id)
    print("  status:", response.status)
    print("  tool batches executed:", len(response.tools or []))
    print(
        "  last_checkpoint_at_message_index:", response.last_checkpoint_at_message_index
    )
    print()
    print("If this run had crashed between tool batches, the DB would still hold")
    print("the state through the most recent checkpoint. /continue resumes from there.")
    print()

    # Demonstrate the unified /continue API. For a COMPLETED run with no new
    # input, this is effectively a no-op resume — but it would advance an
    # INTERRUPTED, ERROR, or RUNNING run from its checkpoint just the same.
    resumed = await agent.acontinue_run(
        run_id=response.run_id,
        session_id=response.session_id,
    )
    print("After /continue (no-op for a COMPLETED run):")
    print("  status:", resumed.status)


if __name__ == "__main__":
    asyncio.run(main())
