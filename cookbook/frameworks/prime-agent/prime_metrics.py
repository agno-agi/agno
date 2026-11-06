"""Inspect Prime's reported usage and Agno's accumulated session metrics."""

from os import getenv

from agno.agents.prime import PrimeAgent
from agno.db.sqlite import SqliteDb

agent = PrimeAgent(
    id="prime-metrics",
    name="Prime Metrics",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    db=SqliteDb(db_file="tmp/prime_metrics.db"),
)

if __name__ == "__main__":
    run = agent.print_response(
        "What is 17 times 3? Reply with just the number.",
        session_id="prime-metrics-demo",
    )
    if run.metrics is not None:
        print(f"Model: {run.model} | Provider: {run.model_provider}")
        print(f"Tokens: {run.metrics.total_tokens} | Cost: {run.metrics.cost}")
        print(
            f"Cache read: {run.metrics.cache_read_tokens} | Cache write: {run.metrics.cache_write_tokens}"
        )
    session = agent.get_session("prime-metrics-demo")
    if session is not None:
        print((session.session_data or {}).get("session_metrics"))
