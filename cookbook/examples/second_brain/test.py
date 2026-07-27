"""
Second Brain - CLI
====================================
Runs the second_brain without starting the server: capture a decision in one
session, then recall it in a new session that shares nothing but the brain.
"""

from uuid import uuid4

from second_brain import notes, second_brain

# ---------------------------------------------------------------------------
# Two sessions that share nothing; identity is pinned on the agent itself.
# ---------------------------------------------------------------------------
CAPTURE_SESSION = f"capture-{uuid4().hex[:8]}"
RECALL_SESSION = f"recall-{uuid4().hex[:8]}"

# ---------------------------------------------------------------------------
# Run: capture a decision, then ask for it back in the other session
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n--- Session 1: capture a decision ---\n")
    second_brain.print_response(
        "I am building quill, a Postgres-backed job queue in Rust. I picked "
        "advisory locks over SELECT FOR UPDATE SKIP LOCKED because our workers "
        "are long-lived. I want terse answers, no bullet lists.",
        session_id=CAPTURE_SESSION,
        stream=True,
    )

    print("\n--- Session 2: a new session, nothing in context ---\n")
    second_brain.print_response(
        "What did I decide about locking in quill, and why?",
        session_id=RECALL_SESSION,
        stream=True,
    )

    print("\n--- Files in the brain ---\n")
    for meta in notes.list():
        print(f"  {meta.path}  ({meta.size_bytes} bytes)\n")
        print(notes.read(meta.path))
