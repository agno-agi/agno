"""AgentOS with a durable job queue: background eval suite runs survive crashes.

With QueueConfig(durable=True), an eval suite run started with
?background=true is accepted as a committed row in the job queue table, as a
background agent run is. Whichever replica's worker claims the job runs the
cases and writes the result onto the suite's eval run - across process
restarts and deploys. Without a durable queue a server killed mid-run leaves
the eval run RUNNING; with one, the run is retried or fails visibly.

Try it:
1. Start this app and start a background suite run:
   curl -X POST "localhost:7777/eval-suites/math-quality/runs?background=true" \
        -H "Content-Type: application/json" -d '{}'
   -> 202 with the eval run, its summary status RUNNING.
2. Poll GET /eval-runs/{id} until the summary status is PASS, FAIL or ERROR.
3. Kill the server mid-run and restart it:
   - max_attempts=1 (the default, at-most-once): the suite is NOT run again.
     After lock_grace_seconds the sweeper marks the eval run ERROR with the
     reason, and /queue/jobs lists the job as failed.
   - max_attempts=2 or higher (at-least-once): the restarted worker (or any
     other replica) reclaims the job and runs the cases again; the poll ends
     PASS or FAIL.
   Either way the eval run is never stuck at RUNNING forever.
4. Operations surface, shared with background agent runs:
   GET  /queue/stats                 - counts by status, oldest queued age
   GET  /queue/jobs?status=failed    - the dead-letter list
   POST /queue/jobs/{id}/requeue     - grant a failed job one more attempt
5. Resubmit safely with an Idempotency-Key header: a duplicate submission
   returns the existing eval run instead of running the suite twice.
6. Delete a background run with DELETE /eval-runs: its ticket is cancelled,
   so the suite stops (or never starts) and the run does not come back.

The queue store defaults to the AgentOS db (the Postgres below). A dedicated
Redis works too: QueueConfig(durable=True, db=RedisDb(...)).

Requirements:
- PostgreSQL running (./cookbook/scripts/run_pgvector.sh)
- OPENAI_API_KEY set
"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.eval import Case, EvalSuite
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, QueueConfig
from agno.tools.calculator import CalculatorTools

db = PostgresDb(
    db_url=getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")
)

agent = Agent(
    name="Math Tutor",
    id="math-tutor",
    model=OpenAIResponses(id="gpt-5.5"),
    description="An agent whose eval suite runs in the background through the durable queue",
    db=db,
    tools=[CalculatorTools()],
    instructions="Use the calculator tools for any arithmetic.",
)

suite = EvalSuite(
    id="math-quality",
    name="Math quality",
    cases=(
        Case(
            name="multiplies",
            agent=agent,
            input="What is 12 times 7?",
            expected_tool_calls=("multiply",),
        ),
        Case(
            name="explains",
            agent=agent,
            input="Explain in one sentence why 2 + 2 = 4.",
            criteria="Gives a short, correct explanation.",
        ),
    ),
)

agent_os = AgentOS(
    description="AgentOS with a durable job queue for eval suite runs",
    agents=[agent],
    eval_suites=[suite],
    db=db,
    queue=QueueConfig(
        durable=True,  # queue table lives in the Postgres above
        # At-most-once by default: a suite run killed mid-flight FAILS VISIBLY
        # and is not run again. Set 2+ to have it reclaimed and run again by
        # any live replica - see "Try it" step 3.
        max_attempts=1,
    ),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="durable_queue_eval_suite:app", reload=True)
