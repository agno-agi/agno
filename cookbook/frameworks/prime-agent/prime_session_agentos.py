"""Serve local Prime conversations with persisted sessions and native resume.

SQLite and an unauthenticated localhost server are used for this local demo.
Use the README's HTTP requests to send two turns to the same session.
"""

from os import getenv

from agno.agents.prime import PrimeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

agent = PrimeAgent(
    id="prime-chat",
    name="Prime Chat",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    db=SqliteDb(db_file="tmp/prime_session_agentos.db"),
    session_dir=".agno/prime-agent-sessions",
    instructions="Keep replies concise. Ask before modifying project files.",
    timeout=120,
)
agent_os = AgentOS(
    id="prime-session-agentos",
    name="Prime Session Demo",
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        app=app, host="127.0.0.1", port=int(getenv("PORT", "7777")), reload=False
    )
