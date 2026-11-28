"""Compact Prime's native context, then continue the same Agno session."""

from os import getenv

from agno.agents.prime import PrimeAgent
from agno.db.sqlite import SqliteDb

SESSION_ID = "prime-compaction-demo"
agent = PrimeAgent(
    id="prime-compaction",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    db=SqliteDb(db_file="tmp/prime_compaction.db"),
)

if __name__ == "__main__":
    agent.print_response(
        "Remember the project codename is Cedar. Reply with OK.", session_id=SESSION_ID
    )
    compacted = agent.compact(SESSION_ID)
    print(f"Compacted: {compacted}")
    agent.print_response("What is the project codename?", session_id=SESSION_ID)
