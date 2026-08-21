"""
Delete Session Cascade
======================

A stored result belongs to its session. `delete_session` and `delete_sessions`
remove the session's index rows and payloads along with the session, scoped to
what the delete was allowed to remove: a delete for one user never touches
another user's payloads, even if it names their session id.

This example runs two users in two sessions, deletes one session as the wrong
user (nothing happens), then as the right user (the session, its index row
and its payload go together), and shows the other user's result untouched.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses

db = SqliteDb(db_file="tmp/delete_session_cascade.db")

TICKETS = "\n".join(
    f"ticket-{i:05d} priority={'P1' if i % 97 == 0 else 'P3'} queue=q{i % 6}"
    for i in range(1, 1201)
)


def list_tickets() -> str:
    """List every open support ticket.

    Returns:
        str: One ticket per line.
    """
    return TICKETS


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[list_tickets],
    offload_tool_results=True,
    markdown=True,
)


def describe(session_id: str) -> None:
    rows = db.get_tool_results_for_session(session_id)
    payloads = sum(
        1
        for row in rows
        if FileSystem(backend=db, namespace=row["namespace"]).read(row["path"])
        is not None
    )
    print(f"   {session_id}: {len(rows)} index row(s), {payloads} payload(s)")


# ---------------------------------------------------------------------------
# Run Agent for two users
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for user_id, session_id in (("alice", "tickets-alice"), ("bob", "tickets-bob")):
        output = agent.run(
            "How many P1 tickets are open? Use search_result.",
            session_id=session_id,
            user_id=user_id,
        )
        print(f"{user_id}: {output.content}")

    print("\nBefore any delete:")
    describe("tickets-alice")
    describe("tickets-bob")

    # The wrong user cannot delete alice's session, so nothing cascades.
    deleted = db.delete_session(session_id="tickets-alice", user_id="bob")
    print(f"\ndelete_session(tickets-alice, user_id=bob) -> {deleted}")
    describe("tickets-alice")

    # The right user removes the session, its index row and its payload together.
    deleted = db.delete_session(session_id="tickets-alice", user_id="alice")
    print(f"\ndelete_session(tickets-alice, user_id=alice) -> {deleted}")
    describe("tickets-alice")
    describe("tickets-bob")
