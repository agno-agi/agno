"""Replay Hermes conversation history saved in Agno's database across turns."""

from os import getenv

from agno.agents.hermes import HermesAgent
from agno.db.sqlite import SqliteDb

agent = HermesAgent(
    name="Hermes Chat",
    model=getenv("HERMES_MODEL"),
    db=SqliteDb(db_file="tmp/hermes_sessions.db"),
    enabled_toolsets=[],
    skip_context_files=True,
    max_iterations=10,
)

if __name__ == "__main__":
    agent.print_response(
        "My favourite programming language is Rust. Acknowledge that in one sentence.",
        session_id="hermes-demo",
        user_id="demo-user",
        stream=True,
    )
    agent.print_response(
        "What is my favourite programming language? Answer in one word.",
        session_id="hermes-demo",
        user_id="demo-user",
        stream=True,
    )
