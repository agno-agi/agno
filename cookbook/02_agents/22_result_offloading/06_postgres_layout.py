"""
PostgreSQL Layout
=================

On PostgreSQL the two tables live in two schemas:

- `agno_tool_results`, the index, is created in your `db_schema` next to the
  sessions, so one database can hold several applications side by side.
- `agno_fs`, the AgentFS payload table, is created in the schema `fs` and is
  shared by every `db_schema` of the database. The namespace of each payload
  therefore carries the schema name, so two applications that reuse a session
  id never share payload rows.

Run the database first:

    ./cookbook/scripts/run_pgvector.sh

This example runs one agent against PostgreSQL, then queries both schemas.
"""

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from sqlalchemy import text

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, db_schema="ai")

ROSTER = "\n".join(
    f"employee-{i:04d},{'engineering' if i % 4 else 'sales'},{'remote' if i % 5 == 0 else 'onsite'}"
    for i in range(1, 1501)
)


def export_roster() -> str:
    """Export the employee roster as CSV.

    Returns:
        str: id,department,location per line.
    """
    return ROSTER


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[export_roster],
    offload_tool_results=True,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent, then look at both schemas
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "postgres-layout"
    output = agent.run(
        "Export the roster and tell me how many sales employees are remote. Use search_result.",
        session_id=session_id,
    )
    print(output.content)

    with db.db_engine.begin() as conn:
        print("\nThe index, in your schema (ai.agno_tool_results):")
        for result_id, namespace, path, size in conn.execute(
            text(
                "SELECT result_id, namespace, path, size_bytes FROM ai.agno_tool_results WHERE session_id = :s"
            ),
            {"s": session_id},
        ):
            print(f"   {result_id}  namespace={namespace}  path={path}  {size} bytes")

        print("\nThe payload, in the shared AgentFS schema (fs.agno_fs):")
        for namespace, path, size, version in conn.execute(
            text(
                "SELECT namespace, path, size_bytes, version FROM fs.agno_fs "
                "WHERE namespace LIKE 'tool-results/postgres-layout-%'"
            ),
        ):
            print(
                f"   namespace={namespace}  path={path}  {size} bytes  version={version}"
            )

    print("\nThe stored run, in your schema, holds only the envelope:")
    session = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    for message in session.runs[-1].messages or []:
        if message.role == "tool" and message.tool_name == "export_roster":
            print(
                f"   stored tool message: {len(str(message.content))} characters (the tool returned {len(ROSTER)})"
            )

    # Clean up: the cascade removes the index row and the payload in fs.agno_fs.
    db.delete_session(session_id=session_id)
    with db.db_engine.begin() as conn:
        left = conn.execute(
            text(
                "SELECT count(*) FROM fs.agno_fs WHERE namespace LIKE 'tool-results/postgres-layout-%'"
            )
        ).scalar()
        print(f"\nAfter delete_session, payload rows left in fs.agno_fs: {left}")
