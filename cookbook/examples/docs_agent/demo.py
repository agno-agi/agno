"""Ask sourced documentation questions and a follow-up in one conversation."""

from uuid import uuid4

from docs_agent import agent

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = str(uuid4())
    for question in (
        "How do I export only the filtered rows from a report?",
        "Can I have that CSV emailed to me every week?",
        "What is your data residency policy?",
    ):
        agent.print_response(question, session_id=session_id, user_id="demo-user")
