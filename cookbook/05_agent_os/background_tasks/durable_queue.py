"""AgentOS with a durable job queue: accepted background runs survive crashes.

With QueueConfig(durable=True), a background run (background=True) is
accepted as a committed row in the job queue table. Whichever replica's worker
claims the job executes it - across process restarts and deploys. A crashed
run is never silently re-executed (max_attempts=1 by default): it is failed
visibly, and an operator can requeue it.

Try it:
1. Start this app and submit a background run:
   curl -X POST localhost:7777/agents/durable-agent/runs \
        -F "message=Write a haiku about queues" -F "background=true"
   -> 202 with run_id; the run row is committed before the response.
2. Poll GET /agents/durable-agent/runs/{run_id} for the result.
3. Kill the server mid-run and restart it: the job is reclaimed or failed
   visibly - never lost, never stuck at RUNNING forever.
4. Operations surface:
   GET  /queue/stats                 - counts by status, oldest queued age
   GET  /queue/jobs?status=failed    - the dead-letter list
   POST /queue/jobs/{id}/requeue     - grant a failed job one more attempt
5. Resubmit safely with an Idempotency-Key header: duplicate submissions
   return the existing run instead of enqueueing twice.
6. STREAMING through the queue: add -F "stream=true" to the submission and the
   response becomes an SSE stream tailing the run's events - while the run
   itself executes durably on whichever replica's worker claims the job.
   Disconnect any time: the run completes regardless and the full output is
   guaranteed via polling; reconnecting replays missed events. Durability
   attaches to the RUN; the stream is the best-effort live view.

The queue store defaults to the AgentOS db (the Postgres below - zero extra
infrastructure). To isolate queue load on a dedicated Redis instead:

    from agno.db.redis import RedisDb

    queue_config = QueueConfig(
        durable=True,
        db=RedisDb(db_url="redis://localhost:6379"),
    )

(Redis acceptance durability depends on persistence config: use AOF
appendfsync everysec/always for Postgres-grade guarantees.)

Requirements:
- PostgreSQL running (./cookbook/scripts/run_pgvector.sh)
- OPENAI_API_KEY set
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    name="Durable Agent",
    id="durable-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    description="An agent whose background runs survive crashes and deploys",
    db=db,
)

agent_os = AgentOS(
    description="AgentOS with a durable job queue",
    agents=[agent],
    db=db,
    queue=QueueConfig(
        durable=True,  # queue table lives in the Postgres above
        max_concurrency=8,  # per replica
        max_queue_depth=1000,  # global bound -> 429 beyond it
    ),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="durable_jobs:app", reload=True)
