"""Durable continuation legs: HITL pause/continue that survives crashes.

A durable background run that pauses for human input parks its queue ticket
as PAUSED. Continuing it with background=true CAS-flips the SAME ticket back
to queued (never a new row - the ticket id IS the run id), merges your tool
confirmations into its payload, and lets whichever replica's worker claims
it drive acontinue_run. The continuation leg gets exactly one execution
(never a silent retry); a crashed leg is failed visibly and an operator
requeue re-drives the same confirmations.

Try it:
1. Start this app and submit a background run that needs confirmation:
   curl -X POST localhost:7777/agents/hitl-agent/runs \
        -F "message=Delete the temp files" -F "background=true" -F "stream=false"
   -> 202; poll GET /agents/hitl-agent/runs/{run_id}?session_id={session_id}
   until status is PAUSED. The queue ticket is now PAUSED too:
   GET /queue/jobs/{run_id}
2. Confirm the tool and continue DURABLY (background=true is the switch):
   curl -X POST localhost:7777/agents/hitl-agent/runs/{run_id}/continue \
        -F "session_id={session_id}" -F "stream=false" -F "background=true" \
        -F 'tools=[{... the paused run's tool dict with "confirmed": true ...}]'
   -> 202 immediately; the ticket is queued again and the continuation leg
   executes on whichever replica claims it. Kill the server after the 202
   and restart: the continuation still runs.
3. Double-click safety: repeat the continue request - it attaches to the
   in-flight continuation (202) or asks you to retry in a moment (409 with
   Retry-After) once the leg is already executing. It never runs twice and
   never drops your confirmations silently.
4. If a worker dies mid-continuation, the leg is swept to failed VISIBLY
   (GET /queue/jobs?status=failed) and POST /queue/jobs/{run_id}/requeue
   re-drives the same merged confirmations.
5. Cancelling a paused run cancels its ticket too; a later continue gets an
   honest 409 instead of resurrecting the run.

Requirements:
- PostgreSQL running (./cookbook/scripts/run_pgvector.sh)
- OPENAI_API_KEY set
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, QueueConfig
from agno.tools import tool


@tool(requires_confirmation=True)
def delete_temp_files(directory: str) -> str:
    """Delete temporary files in a directory. Requires human confirmation."""
    return f"Deleted temp files in {directory}"


db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    name="HITL Agent",
    id="hitl-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[delete_temp_files],
    instructions="Use delete_temp_files when asked to delete or clean up files.",
)

agent_os = AgentOS(
    agents=[agent],
    db=db,
    queue=QueueConfig(durable=True),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="durable_continue:app", port=7777)
