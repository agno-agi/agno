"""
Offload Tool Results
====================

A long agentic run dies of its own tool output. One large search result sits
in the message list forever, re-sent on every later model call.

`offload_tool_results=True` makes the transcript hold a pointer instead of a
payload. A result longer than 16,000 characters is written to the database and
the message gets a short envelope: a head preview and a `result_id`. The agent
gets two tools to go back for the rest, `read_result` and `search_result`, and
the full bytes stay recoverable.

Nothing is summarized away, there is no model call on the write path, and
every read back is capped.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# A tool that returns far more than anyone wants in a transcript.
CATALOG = "\n".join(
    f"SKU-{i:05d}\tpart-{i % 37}\tqty={i * 7 % 91}\twarehouse={'ABCDE'[i % 5]}"
    for i in range(1, 4001)
)


def fetch_catalog() -> str:
    """Fetch the full parts catalog as a tab-separated table.

    Returns:
        str: one row per SKU.
    """
    return CATALOG


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="tmp/offloading.db"),
    tools=[fetch_catalog],
    offload_tool_results=True,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    output = agent.run(
        "Fetch the catalog, then tell me which warehouse SKU-00042 is in and how "
        "many rows the catalog has. Use search_result rather than re-fetching.",
        session_id="offloading-basic",
    )
    print(output.content)

    print("\n--- what the transcript actually held ---")
    for message in output.messages or []:
        if message.role == "tool":
            print(
                f"tool message length: {len(str(message.content))} chars (the full result was {len(CATALOG)})"
            )
            print(str(message.content)[:400])
            break
