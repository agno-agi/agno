"""
Second Brain - Drive It From the CLI
====================================
Runs the agent from second_brain.py without starting the server: capture a
decision in one session, then ask for it back in a brand new session that shares
no history. Everything the second session knows came from the store.

Run it twice. The second run is a new process, and it reads the note the first
one left before writing anything:

    python cookbook/examples/second_brain/test.py
"""

from uuid import uuid4

from second_brain import notes, second_brain

# ---------------------------------------------------------------------------
# Create the run: one user, two sessions that share nothing
# ---------------------------------------------------------------------------
# Notes live under brain/{user_id}, so every run needs a user_id.
USER_ID = "alice@example.com"
CAPTURE_SESSION = f"capture-{uuid4().hex[:8]}"
RECALL_SESSION = f"recall-{uuid4().hex[:8]}"

# ---------------------------------------------------------------------------
# Run: capture a decision, then ask for it back in the other session
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"User:  {USER_ID}")

    print("\n--- Session 1: capture a decision ---\n")
    second_brain.print_response(
        "I am building Harbor, a Postgres-backed job queue in Rust. I picked "
        "advisory locks over SELECT FOR UPDATE SKIP LOCKED because our workers "
        "are long-lived. I want terse answers, no bullet lists.",
        user_id=USER_ID,
        session_id=CAPTURE_SESSION,
        stream=True,
    )

    print("\n--- Session 2: a new session, nothing in context ---\n")
    second_brain.print_response(
        "What did I decide about locking in Harbor, and why?",
        user_id=USER_ID,
        session_id=RECALL_SESSION,
        stream=True,
    )

    print("\n--- Files in this user's brain ---\n")
    for meta in notes.resolve(user_id=USER_ID).list():
        print(f"  {meta.path}  ({meta.size_bytes} bytes)")
