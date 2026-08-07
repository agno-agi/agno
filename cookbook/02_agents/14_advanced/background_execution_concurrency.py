"""
Example demonstrating the concurrency limit for background runs.

Background runs (background=True) are accepted immediately and persisted with
PENDING status, but only a bounded number execute at once per process. Runs
beyond the limit wait in line as PENDING and start automatically when a slot
frees up. This prevents a burst of submissions from executing all at once.

The limit is process-wide and shared across agents, teams and workflows.
Configure it one of three ways:
- set_background_max_concurrency(n) programmatically (used below)
- AgentOS(queue=QueueConfig(max_concurrency=n)) when serving over AgentOS
- the AGNO_BACKGROUND_MAX_CONCURRENCY environment variable (default: 32)

Requirements:
- PostgreSQL running (./cookbook/scripts/run_pgvector.sh)
- OPENAI_API_KEY set

Usage:
    .venvs/demo/bin/python cookbook/02_agents/14_advanced/background_execution_concurrency.py
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.run.base import RunStatus
from agno.run.concurrency import set_background_max_concurrency

db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    session_table="background_concurrency_sessions",
)

agent = Agent(
    name="BoundedBackgroundAgent",
    model=OpenAIResponses(id="gpt-5.5"),
    description="An agent whose background runs execute under a concurrency cap",
    db=db,
)


async def main():
    # Allow at most 2 background runs to execute at once in this process.
    # Additional runs are accepted and wait in line as PENDING.
    set_background_max_concurrency(2)

    # Submit 5 background runs — all are accepted immediately
    questions = [
        "What is the capital of France? One sentence.",
        "What is the capital of Japan? One sentence.",
        "What is the capital of Brazil? One sentence.",
        "What is the capital of Kenya? One sentence.",
        "What is the capital of Canada? One sentence.",
    ]
    outputs = []
    for i, question in enumerate(questions):
        # One session per run: concurrent background runs sharing one session
        # can clobber each other's status updates (fixed in the durable run
        # queue PR chain; distinct sessions are also the realistic shape).
        run_output = await agent.arun(
            question, background=True, session_id=f"bg-concurrency-{i}"
        )
        print(f"Accepted run {run_output.run_id} with status {run_output.status}")
        outputs.append(run_output)

    # Poll until all runs complete. At any moment at most 2 are RUNNING;
    # the rest wait as PENDING until a slot frees up.
    print("\nPolling until all runs complete...")
    pending = {output.run_id: output.session_id for output in outputs}
    for second in range(120):
        await asyncio.sleep(1)
        statuses = []
        for run_id, session_id in list(pending.items()):
            result = await agent.aget_run_output(run_id=run_id, session_id=session_id)
            if result is not None and result.status in (
                RunStatus.completed,
                RunStatus.error,
            ):
                print(f"  [{second + 1}s] Run {run_id} finished: {result.status}")
                del pending[run_id]
            elif result is not None:
                statuses.append(str(result.status))
        if statuses:
            print(f"  [{second + 1}s] In progress: {statuses}")
        if not pending:
            break

    if pending:
        print(f"\nTimed out waiting for {len(pending)} run(s): {sorted(pending)}")
    else:
        print("\nAll runs completed!")


if __name__ == "__main__":
    asyncio.run(main())
