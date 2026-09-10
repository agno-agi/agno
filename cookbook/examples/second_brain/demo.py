"""Exercise actual learning tools, fresh conversations, and a correction.
Use --recall-only in a new process to inspect the persisted corrected state.
"""

import sys
from uuid import uuid4

from second_brain import brain, second_brain

# ---------------------------------------------------------------------------
# Create the learning conversation
# ---------------------------------------------------------------------------
USER = "demo-owner"
PROMPTS = [
    "My name is Alex. Remember that I prefer short updates with action items first. "
    "Track the Harbor onboarding project and Jen, its reviewer. "
    "Jen is the project lead. Use your learning tools to retain these facts.",
    "Who leads Harbor, who reviews it, and how do I like updates?",
    "Correction: Maya is the Harbor project lead. Jen is still the reviewer. "
    "Replace the old leadership fact in entity memory. Keep the other facts.",
]
RECALL = "Who currently leads Harbor, who reviews it, and how do I like updates?"

# ---------------------------------------------------------------------------
# Run: every prompt starts a new conversation with the same user
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--recall-only" not in sys.argv:
        for prompt in PROMPTS:
            second_brain.print_response(prompt, user_id=USER, session_id=str(uuid4()))
    second_brain.print_response(RECALL, user_id=USER, session_id=str(uuid4()))
    print(brain.build_context(user_id=USER, message="Harbor"))
