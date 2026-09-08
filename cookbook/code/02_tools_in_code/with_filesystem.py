"""
CodeMode - Composing with the agent filesystem
==============================================

`FileSystem.tools()` composes into CodeMode as the `filesystem` handle, so the
agent can compute in the kernel and write durable notes to the database in the
same cell. The same FileSystem also backs CodeMode's own snapshots when passed
as `fs=`.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.tools.code import CodeMode

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/code_mode.db")
notes = FileSystem(backend=db, namespace="notes")

code = CodeMode(tools=[notes.tools()])

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[code],
    instructions=[
        "Use the code environment to compute, and the filesystem handle to keep durable notes.",
        notes.instructions(),
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        agent.print_response(
            "Compute the mean and standard deviation of [12, 15, 9, 22, 30, 18, 7] in "
            "the code environment, then append a one-line summary to "
            "'stats/summary.md' through the filesystem handle. Tell me what you wrote.",
            session_id="code-mode-filesystem",
        )
    finally:
        code.shutdown()
