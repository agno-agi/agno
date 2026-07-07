"""
Compliance Agent With Persistent Notes
======================================

Demonstrates a policy-review agent that stores audit notes in long-term memory.

The agent reviews simple data-handling requests, records its ruling in memory,
and recalls prior decisions in later sessions.

Key concepts:
- enable_agentic_memory: agent writes notes when a ruling is made
- user_id: scopes compliance notes to an organization or reviewer
- Memories survive across sessions for audit trails

Example prompts to try:
- "Can we store customer emails in a shared spreadsheet?"
- "What did we decide about storing customer emails?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/compliance_notes.db")
org_id = "acme-corp"

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a data-compliance reviewer for a small SaaS company.

## Policy (simplified)
- Customer emails may be stored only in approved CRM systems with access controls.
- Shared spreadsheets and public channels are not approved for PII.
- When you make a ruling, store a short audit note in memory that includes:
  the request topic, your decision (approved/denied), and the reason.

## Workflow
1. Evaluate the request against the policy.
2. Give a clear approved/denied answer with a one-line rationale.
3. Save an audit note to memory for future reference.
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    enable_agentic_memory=True,
    instructions=instructions,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Review request and persist ruling ===")
    agent.print_response(
        "Can we store customer emails in a shared spreadsheet for the sales team?",
        user_id=org_id,
        session_id="compliance_review_1",
        stream=True,
    )

    print("\n=== Later session: recall prior ruling ===")
    agent.print_response(
        "What did we decide about storing customer emails?",
        user_id=org_id,
        session_id="compliance_review_2",
        stream=True,
    )

    print("\n=== Audit notes in memory ===")
    for memory in agent.get_user_memories(user_id=org_id):
        print(f"- {memory.memory}")