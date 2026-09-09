"""
Team Brain - CLI
================
Runs the team brain without starting the server: log a decision as one teammate,
then ask the librarian what the team has decided.
"""

import asyncio

from team_brain import DECISION_LOG, fs, librarian, remember

# ---------------------------------------------------------------------------
# Create the run: one decision, logged as one teammate
# ---------------------------------------------------------------------------
# Over MCP the author comes from the caller's token. Here there is no token, so
# it is passed in directly.
AUTHOR = "alice"
DECISION = "We ship the queue on Postgres, not SQS, because we already run Postgres."

# ---------------------------------------------------------------------------
# Run: log a decision, then ask what the log says
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n--- Log a decision ---\n")
    print(asyncio.run(remember(DECISION, user_id=AUTHOR)))

    print("\n--- Ask the librarian ---\n")
    librarian.print_response("What has the team decided so far?", stream=True)

    print(f"\n--- {DECISION_LOG} ---\n")
    print(fs.read(DECISION_LOG))
