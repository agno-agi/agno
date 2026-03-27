"""
Session Context Compaction
==========================

Force early context compaction with a low message limit, then inspect the
stored summary and the response generated after compaction.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.session import ContextCompactionManager
from agno.db.postgres import PostgresDb

SESSION_ID = "session_compaction_demo"

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


def print_heading(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print(f"{'=' * 60}\n")


agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    session_id=SESSION_ID,
    add_history_to_context=True,
    db=db,
    add_session_summary_to_context=True,
    context_compaction_manager=ContextCompactionManager(
        compact_message_limit=4,
        keep_last_n_runs=1,
    ),
    instructions=[
        "Keep responses concise.",
        "Preserve concrete technical details when the user asks for a recap.",
    ],
    markdown=True,
)


def run_turn(title: str, prompt: str) -> None:
    print_heading(title)
    response = agent.run(prompt)
    print(response.content)


if __name__ == "__main__":
    run_turn(
        "TURN 1: Initial context",
        (
            "We are debugging a FastAPI webhook service. "
            "It runs in us-east-1, uses Redis for deduplication, and retries failed jobs 3 times."
        ),
    )

    run_turn(
        "TURN 2: More details",
        (
            "Add these constraints: the p95 latency target is under 250 ms, "
            "and the on-call team is Platform Infra."
        ),
    )

    print_heading("TURN 3: Trigger compaction with a low message limit")
    print(
        "The `compact_message_limit` is 4, so this turn should compact older context first.\n"
    )
    response_after_compaction = agent.run(
        "Give me a short incident checklist for this service."
    )
    print(response_after_compaction.content)

    session = agent.get_session(session_id=SESSION_ID)
    summary = agent.get_session_summary(session_id=SESSION_ID)

    print_heading("STORED COMPACTED SUMMARY")
    if summary is not None:
        print(summary.summary)
    else:
        print("No compacted summary found.")

    if session is not None:
        print(f"\nLast compacted run id: {session.get_last_compacted_run_id()}")

    print_heading("TURN 4: Response after compaction")
    follow_up_response = agent.run(
        "What details should you remember before answering future debugging questions?"
    )
    print(follow_up_response.content)
