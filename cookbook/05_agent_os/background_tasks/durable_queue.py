"""AgentOS with a durable job queue: accepted background runs survive crashes.

With QueueConfig(durable=True), a background run (background=True) is
accepted as a committed row in the job queue table. Whichever replica's worker
claims the job executes it - across process restarts and deploys. What
happens to a run whose worker CRASHES is a choice: with the default
max_attempts=1 it fails visibly and is never silently re-executed (its side
effects may already have happened); with max_attempts=2+ a live replica
reclaims and re-executes it automatically. See "Try it" step 3.

Try it:
1. Start this app and submit a background run:
   curl -X POST localhost:7777/agents/durable-agent/runs \
        -F "message=Write a haiku about queues" -F "background=true" \
        -F "stream=false"
   -> 202 with run_id and session_id; the run row is committed before the response.
2. Poll GET /agents/durable-agent/runs/{run_id}?session_id={session_id} for the result.
3. Kill the server mid-run and restart it. What happens next is the most
   important knob in this cookbook:
   - max_attempts=1 (the default, at-most-once): the run is NOT re-executed.
     After lock_grace_seconds the sweeper fails it visibly - the poll shows
     ERROR with the reason, /queue/jobs lists it as failed, and an operator
     can requeue it. This is the right default for runs with side effects
     (emails, payments): a killed run may have already acted, and silent
     re-execution would act twice.
   - max_attempts=2 or higher (at-least-once): the restarted worker (or any
     other replica) reclaims the stale job and re-executes it automatically -
     kill the server mid-run and watch the run complete anyway. Retries are
     safe: a still-alive "dead" worker is fenced from corrupting the retry's
     run row or event stream.
   Either way the run is never lost and never stuck at RUNNING forever.
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
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, QueueConfig

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
        # At-most-once by default: a run killed mid-flight FAILS VISIBLY and
        # is never silently re-executed (its side effects may already have
        # happened). Set 2+ to have a crashed run reclaimed and re-executed
        # automatically by any live replica - see "Try it" step 3.
        max_attempts=1,
    ),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="durable_queue:app", reload=True)
