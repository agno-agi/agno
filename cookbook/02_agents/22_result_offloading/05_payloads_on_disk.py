"""
Payloads on Disk
================

By default the stored payload goes to AgentFS on the agent's database. The
`fs` setting points payloads at any AgentFS backend instead: a local
directory, a different table, a different database. The index rows stay in
`agno_tool_results` on the agent's db either way, and carry the namespace and
path of each payload, so the read-back tools and the session-delete cascade
find it.

This example writes payloads to a local directory and lists the files it
leaves behind. One caveat to know: a process that never built a store with
this `fs` (a separate cleanup script, say) cannot reach these files when it
deletes the session; it removes the index rows and logs exactly which payload
paths it could not reach.
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses
from agno.offload import ResultStore

db = SqliteDb(db_file="tmp/payloads_on_disk.db")
PAYLOAD_DIR = "tmp/offloaded_payloads"

MANIFEST = "\n".join(
    f"{i:05d},container-{i % 211},{(i * 7) % 1000}kg,{'cold' if i % 3 == 0 else 'dry'}"
    for i in range(1, 1201)
)


def load_shipping_manifest() -> str:
    """Load the full shipping manifest as CSV.

    Returns:
        str: id,container,weight,storage per line.
    """
    return MANIFEST


# ---------------------------------------------------------------------------
# Create Agent with payloads on a local directory
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[load_shipping_manifest],
    offload_tool_results=ResultStore(
        fs=FileSystem(backend=LocalFileSystem(root=PAYLOAD_DIR))
    ),
    markdown=True,
)


def list_payload_files() -> None:
    found = False
    for directory, _, files in os.walk(PAYLOAD_DIR):
        for name in files:
            path = os.path.join(directory, name)
            print(f"   {path} ({os.path.getsize(path)} bytes)")
            found = True
    if not found:
        print("   (no files)")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "payloads-on-disk"
    output = agent.run(
        "Load the shipping manifest and tell me how many rows need cold storage. Use search_result.",
        session_id=session_id,
    )
    print(output.content)

    print("\nIndex rows stay on the agent's database:")
    for row in db.get_tool_results_for_session(session_id):
        print(
            f"   {row['result_id']} -> {row['namespace']}/{row['path']} ({row['size_bytes']} bytes)"
        )

    print(f"\nPayload files under {PAYLOAD_DIR}:")
    list_payload_files()

    # Deleting the session removes the index rows and, through the store this
    # process built, the files as well.
    db.delete_session(session_id=session_id)
    print("\nAfter delete_session:")
    print(f"   index rows: {len(db.get_tool_results_for_session(session_id))}")
    list_payload_files()
