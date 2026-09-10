"""AgentOS durable queue with one live run per session, in submission order.

Two background submissions to the same session used to execute concurrently:
the second loaded its context before the first had written anything, and
session-state writes were last-writer-wins. With the durable queue,
QueueConfig(queue_per_session=True) (the default) gives every session its
own FIFO line inside the queue: a job is claimed only while it is the oldest
non-terminal job of its session and no sibling is running. Different
sessions still run concurrently, up to max_concurrency.

Try it:
1. Start this app and submit two background runs to ONE session, back to
   back (the second submission goes out before the first run completes):
   curl -X POST localhost:7777/agents/ordered-agent/runs \
        -F "message=Pick a random city and remember it" \
        -F "session_id=demo-session" -F "background=true" -F "stream=false"
   curl -X POST localhost:7777/agents/ordered-agent/runs \
        -F "message=Which city did you pick? Answer in one word" \
        -F "session_id=demo-session" -F "background=true" -F "stream=false"
   -> both answer 202 immediately with a run_id; PENDING is the accepted,
      not-yet-executing state.
2. Poll the second run while the first is still running:
   GET /agents/ordered-agent/runs/{run_id}?session_id=demo-session
   It stays PENDING until the first run reaches a terminal state, then flips
   to RUNNING and completes. Its answer refers to the city the first run
   chose, which is the point: it ran after the first run, with its context.
3. Submit a run to a different session_id while demo-session is busy. It is
   claimed right away: the line is per session, not global.
4. A run paused for human-in-the-loop approval holds its session's line.
   Successors wait until the paused run is continued or cancelled, because
   their input most likely refers to its outcome. If a session looks stuck,
   check for a paused head first:
   GET /queue/jobs?session_id=demo-session (admin)
5. Clients can discover the behaviour without admin access:
   GET /config -> "queue": {"durable": true, "queue_per_session": true}
   queue_per_session reads true only when a durable queue enforces it.

Set queue_per_session=False to restore fully concurrent claiming across
submissions to one session.

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
    name="Ordered Agent",
    id="ordered-agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    description="An agent whose background runs execute one at a time per session, in order",
    db=db,
    add_history_to_context=True,
)

agent_os = AgentOS(
    description="AgentOS durable queue with one live run per session",
    agents=[agent],
    db=db,
    queue=QueueConfig(
        durable=True,  # the queue table lives in the Postgres above
        # One live run per session, FIFO by submission. This is the default;
        # it is spelled out here because it is what this cookbook demonstrates.
        queue_per_session=True,
        max_concurrency=8,  # per replica, across sessions
    ),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="queue_per_session:app", reload=True)
