"""Personal Agent: capture the tutorial project, then recall from durable notes.
Run again with --recall-only to verify recall after a process restart.
"""

import sys
from uuid import uuid4

from personal_agent import agent, fs

# ---------------------------------------------------------------------------
# Create the tutorial conversation
# ---------------------------------------------------------------------------
USER = "tutorial-user"
BRIEF = """I'm updating our customer onboarding guide. The goal is to help new users
finish setup without asking support. Jen is reviewing the draft.

Save this project and two next steps: send Jen the draft by Thursday,
and test the setup steps with a new user by Friday.
Keep my updates short, with action items first."""
UPDATE = """I sent Jen the draft.
We decided to use a checklist instead of a video because it's easier
to keep up to date. Save that decision and the reasoning."""
RECALL = """Where did we leave the onboarding guide? What's next, and why did we
choose a checklist?"""

# ---------------------------------------------------------------------------
# Run the same agent; a fresh session cannot see the capture conversation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--recall-only" not in sys.argv:
        session = str(uuid4())
        agent.print_response(BRIEF, user_id=USER, session_id=session)
        agent.print_response(UPDATE, user_id=USER, session_id=session)
    agent.print_response(RECALL, user_id=USER, session_id=str(uuid4()))
    for document in fs.resolve(user_id=USER).list():
        print(document.path)
        print(fs.resolve(user_id=USER).read(document.path))
