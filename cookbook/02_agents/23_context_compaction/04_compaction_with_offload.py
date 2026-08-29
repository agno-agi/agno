"""
Compaction with Result Offloading
=================================

The two context layers compose. Offloading keeps big tool results out of the
transcript from the start (a pointer plus preview instead of the payload);
compaction manages whatever still accumulates. Offloaded envelopes are never
elided or summarized away — the result ids survive verbatim, and the summary
is followed by a survival notice listing which stored results are still
readable with read_result.

Run: .venvs/demo/bin/python cookbook/02_agents/23_context_compaction/04_compaction_with_offload.py
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

INVENTORY = "\n".join(
    f"SKU-{i:05d}\tpart-{i % 37}\tqty={i * 7 % 91}\twarehouse={'ABCDE'[i % 5]}" for i in range(1, 4001)
)


def fetch_inventory() -> str:
    """Fetch the full inventory as a tab-separated table.

    Returns:
        str: one row per SKU.
    """
    return INVENTORY


agent = Agent(
    id="compaction-offload-demo",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction.db"),
    tools=[fetch_inventory],
    add_history_to_context=True,
    offload_tool_results=True,
    compaction=Compaction(context_window=8_000),
    markdown=True,
)

session_id = "compaction-offload-session"

agent.print_response(
    "Fetch the inventory and tell me which warehouse holds the most stock.",
    session_id=session_id,
)
agent.print_response(
    "Now explain, in detail, how you would design a weekly rebalancing plan across warehouses.",
    session_id=session_id,
)
agent.print_response(
    "And what SKU did warehouse A hold the most of? Read it back from the stored result if needed.",
    session_id=session_id,
)
