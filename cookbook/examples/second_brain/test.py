"""
Second Brain - CLI
====================================
Runs the second_brain without starting the server: capture a
decision in one session, then recall in a new session.
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
    brain = notes.resolve(user_id=USER_ID)
    for meta in brain.list():
        print(f"  {meta.path}  ({meta.size_bytes} bytes)\n")
        print(brain.read(meta.path))
