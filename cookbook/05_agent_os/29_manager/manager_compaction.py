"""Keep a long conversation with Super Agent inside the context window.

OSManager(compaction=...) compacts Super Agent's conversation: its older messages
are stored as they were and replaced in context by a summary, and Super Agent can
search what was stored with search_compacted_history. It is off by default.

- compaction=True compacts only when the model rejects a request as too long.
- A Compaction sets the size to compact at. Every turn since the last compaction
  is then sent, not only the last num_history_runs.

This example sets a low size so a few pasted notes are enough to compact. A real
deployment sets one near its model's context window. It runs the conversation in
this process: three facts, five pasted notes, then a question about the facts.
It prints each compaction and the searches Super Agent made to answer.

Platform Builder is not compacted. Compaction needs SqliteDb or PostgresDb.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_compaction.py
"""

from pathlib import Path
from uuid import uuid4

from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from fastapi.testclient import TestClient

SESSION = f"manager-compaction-{uuid4().hex[:8]}"

Path("tmp").mkdir(exist_ok=True)
db = SqliteDb(db_file="tmp/manager_compaction.db")
agent_os = AgentOS(
    name="Compaction demo",
    db=db,
    manager=OSManager(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        access_docs=False,
        # Super Agent's own prompt and tools take about 12,000 tokens of this.
        compaction=Compaction(compact_at_tokens=20_000, uncompacted_runs=1),
    ),
    telemetry=False,
)
app = agent_os.get_app()

NOTE = " ".join(
    f"Line {i}: the review of shipment batch {i} found no blocking issue and the carrier confirmed the slot."
    for i in range(150)
)


def ask(client: TestClient, message: str) -> dict:
    response = client.post(
        "/teams/superagent/runs",
        data={
            "message": message,
            "session_id": SESSION,
            "user_id": "sam",
            "stream": "false",
        },
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    with TestClient(app) as client:
        ask(
            client,
            "Keep these for later: the contact is Idris Okonkwo, the account number is "
            "77-4419-KX, and we ship on the 14th from the Rotterdam depot. Just confirm.",
        )
        for number in range(1, 6):
            ask(client, f"Notes, part {number}. Reply only with 'noted'.\n\n{NOTE}")
            print(f"Sent notes part {number}")

        answer = ask(
            client,
            "Who is the contact, what is the account number, and when and from where do we ship?",
        )

    print("\nCompactions of this conversation:")
    for record in reversed(db.get_compactions_for_session(SESSION)):
        print(
            f"  folded {record['messages_compacted']} messages: "
            f"{record['tokens_before']} -> {record['tokens_after']} tokens"
        )

    print("\nAnswer after compaction:")
    print("  " + str(answer.get("content")).replace("\n", "\n  "))
    for tool in answer.get("tools") or []:
        if tool.get("tool_name") == "search_compacted_history":
            print(f"\nSearched the stored messages for: {tool.get('tool_args')}")
