"""Persist an Agno conversation and resume its native Prime Agent session."""

from os import getenv

from agno.agents.prime import PrimeAgent
from agno.db.sqlite import SqliteDb

agent = PrimeAgent(
    id="prime-chat",
    name="Prime Chat",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    db=SqliteDb(db_file="tmp/prime_agent.db"),
)

if __name__ == "__main__":
    agent.print_response(
        "Remember that my favorite color is blue.", session_id="prime-demo", stream=True
    )
    agent.print_response(
        "What is my favorite color?", session_id="prime-demo", stream=True
    )
