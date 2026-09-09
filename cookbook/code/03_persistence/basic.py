"""
CodeMode - State that survives the process
==========================================

Pass `fs=` and CodeMode pickles each top-level variable independently into
AgentFS after every successful cell. The database is the state: a kernel that
died, was evicted, or lives in a process that has since exited comes back with
its variables restored, and the model is told what came back in-band:

    <code_mode_restored>
    Restored 3 variables: frames, world_model, notes.
    Not restored:
    - client: TypeError: cannot pickle '_thread.lock' object
    </code_mode_restored>

Every variable that did not come back is named with its reason, so a value
refused for its size reads differently from one that cannot be pickled at all.

Restore runs BEFORE the live toolkit handles are rebound, so a stale pickled
handle from last week always loses to this run's live one.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.tools.code import CodeMode

SESSION_ID = "code-mode-persistence"

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/code_mode.db")
# The snapshot caps count stored bytes and are lowered at setup to whatever this
# store allows, so give the store room for the caps you want.
snapshots = FileSystem(
    backend=db,
    namespace="code-mode",
    max_file_bytes=2_000_000,
    max_namespace_bytes=64_000_000,
)

code = CodeMode(fs=snapshots)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[code],
    instructions="Keep working state in named variables in the code environment.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        agent.print_response(
            "In the code environment, create a variable named `readings` holding the "
            "list [3, 1, 4, 1, 5, 9, 2, 6] and a variable named `notes` holding the "
            "string 'first pass'. Confirm what you stored.",
            session_id=SESSION_ID,
        )

        # Kill the kernel: everything in memory is gone, only the snapshot remains.
        code.close()  # flush a final snapshot
        code.shutdown(SESSION_ID)  # then kill the kernel

        output = agent.run(
            "What is in `readings` and `notes`? Report their sum and the note text.",
            session_id=SESSION_ID,
        )
        print(output.content)

        # The restore notice travels in-band to the model, as the first part of
        # the next execute result. Show it here so the round trip is visible.
        for message in output.messages or []:
            if message.role == "tool" and "<code_mode_restored>" in str(
                message.content
            ):
                print("\n--- what the model was told ---")
                print(
                    str(message.content).split("</code_mode_restored>")[0]
                    + "</code_mode_restored>"
                )
                break
    finally:
        code.shutdown()
