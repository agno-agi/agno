"""
Where Results Live
==================

An offloaded result lands in three places, and only one of them is the
session:

1. The session row holds the envelope: a preview and a result id. That is
   all the model ever sees again, and all that is re-sent on later turns.
2. The full text goes to AgentFS, the agent's file store. On SQLite that is
   the `agno_fs` table in the same database file as the sessions.
3. One index row per result goes to the `agno_tool_results` table: where the
   payload is (namespace and path), which session and run it belongs to, its
   size, a preview, and an optional expiry.

Nothing is lost on the way: a tool hook still sees the whole result, and the
payload is readable through the file store. Only what a model reads changes.

This example runs one agent, then opens each place and shows what it holds.
"""

from typing import Any, Callable, Dict

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from sqlalchemy import text

db = SqliteDb(db_file="tmp/where_results_live.db")

# A tool whose output is far longer than the 16,000-character threshold.
ACCESS_LOG = "\n".join(
    f"2026-08-21T10:{i // 60:02d}:{i % 60:02d}Z GET /api/orders/{i} status={'500' if i == 777 else '200'} ms={i % 90}"
    for i in range(1, 1501)
)

seen_by_hook: Dict[str, int] = {}


def read_access_log() -> str:
    """Read today's access log.

    Returns:
        str: One request per line.
    """
    return ACCESS_LOG


def record_result_size(
    function_name: str, function_call: Callable, arguments: Dict[str, Any]
) -> Any:
    # A tool hook runs around the tool itself and sees the full result. The
    # envelope is what the model sees; hooks, metrics and your code are not
    # on that side of the line.
    result = function_call(**arguments)
    seen_by_hook[function_name] = len(str(result))
    return result


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[read_access_log],
    tool_hooks=[record_result_size],
    offload_tool_results=True,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent, then open each place the result went
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "where-results-live"
    output = agent.run(
        "Read the access log and tell me which request returned a 500. Use search_result.",
        session_id=session_id,
    )
    print(output.content)

    print("\n1. The session row: the envelope, not the payload")
    session = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    stored_run = session.runs[-1]
    for message in stored_run.messages or []:
        if message.role == "tool" and message.tool_name == "read_access_log":
            print(
                f"   stored tool message: {len(str(message.content))} characters (the tool returned {len(ACCESS_LOG)})"
            )
            print("   " + str(message.content).split("\n")[0])
    print(
        f"   RunOutput.tools[0].result holds the same envelope: {len(str(output.tools[0].result))} characters"
    )
    print(
        f"   the tool hook saw the full result: {seen_by_hook['read_access_log']} characters"
    )

    print("\n2. The index row in agno_tool_results")
    rows = db.get_tool_results_for_session(session_id)
    row = rows[0]
    for key in (
        "result_id",
        "namespace",
        "path",
        "session_id",
        "run_id",
        "tool_name",
        "size_bytes",
        "line_count",
    ):
        print(f"   {key}: {row[key]}")

    print("\n3. The payload in AgentFS (table agno_fs, same database file)")
    payload = FileSystem(backend=db, namespace=row["namespace"]).read(row["path"])
    print(
        f"   read back {len(payload or '')} characters; identical to the tool output: {payload == ACCESS_LOG}"
    )

    print("\nThe same three places, counted with plain SQL")
    with db.db_engine.begin() as conn:
        sessions = conn.execute(
            text("SELECT count(*) FROM agno_sessions WHERE session_id = :s"),
            {"s": session_id},
        )
        index_rows = conn.execute(
            text("SELECT count(*) FROM agno_tool_results WHERE session_id = :s"),
            {"s": session_id},
        )
        payloads = conn.execute(
            text("SELECT count(*), sum(size_bytes) FROM agno_fs WHERE namespace = :n"),
            {"n": row["namespace"]},
        )
        print(f"   agno_sessions rows: {sessions.scalar()}")
        print(f"   agno_tool_results rows: {index_rows.scalar()}")
        count, size = payloads.fetchone()
        print(f"   agno_fs rows in this session's namespace: {count}, {size} bytes")
