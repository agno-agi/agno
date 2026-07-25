"""
Durable Records - Basic
=======================
Deduplicate work with a record log. The agent calls check_lines before it
acts and append_file after. The log matches on exact lines and outlives the
process, so a recurring job never repeats work it has already done.

This example processes two overlapping ticket batches. The second pass acts
only on the genuinely new ticket.
"""

from typing import List
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_records_{uuid4().hex}.db"

fs = FileSystem(SqliteDb(db_file=DB_FILE))

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[fs.tools()],
    instructions="You triage support tickets.",
)


def process_batch(batch: List[str]) -> None:
    # The directory the agent checks must match where it appends the records
    # (seen/). A mismatched directory returns everything as missing, which is
    # indistinguishable from a fresh store, and the work gets silently redone.
    agent.print_response(
        "Triage this batch of tickets: " + ", ".join(batch) + ". "
        "First call check_lines with directory='seen' to find which ids you have "
        "already triaged. Triage only the missing ones (triaging = naming them in "
        "your reply), then record the newly triaged ids with append_file to "
        "seen/2026-07-24.md, one id per line. Reply with exactly which ids you "
        "triaged this run and which you skipped as already done."
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("pass 1: fresh store, both tickets are new")
    process_batch(["TICKET-101", "TICKET-102"])

    print("pass 2: overlapping batch, only TICKET-103 is new")
    process_batch(["TICKET-101", "TICKET-102", "TICKET-103"])

    print("the record log now contains:")
    print(fs.read("seen/2026-07-24.md"))
