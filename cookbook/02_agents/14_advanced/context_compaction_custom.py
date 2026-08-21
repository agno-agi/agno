"""
Context Compaction with Custom Instructions
============================================
Advanced context compaction with custom summarization prompts.

This example shows how to customize the compaction behavior:
- compact_context_instructions: Custom prompts for domain-specific summarization
- compact_context_preserve_user_budget: Token budget for preserving user messages verbatim
- compact_context_keep_recent: How many recent messages to keep intact
- compact_context_message_limit: Trigger by message count instead of tokens

Use case: IT support agent working a ticket across days. Turns are short but
numerous. Custom instructions ensure ticket IDs, error codes, and tried steps
are never lost in the summary.

See also: context_compaction.py for basic usage.
"""

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.toolkit import Toolkit

# ---------------------------------------------------------------------------
# Mock Tools (simulating a helpdesk system)
# ---------------------------------------------------------------------------


class HelpdeskTools(Toolkit):
    """Simple helpdesk tools for the demo."""

    def __init__(self):
        super().__init__(name="helpdesk")
        self.register(self.check_service_status)
        self.register(self.search_runbook)

    def check_service_status(self, service: str) -> str:
        """Check the status of a service."""
        return f"Service '{service}' is running. Version: 3.2.1, Uptime: 4d 12h"

    def search_runbook(self, query: str) -> str:
        """Search the runbook for troubleshooting steps."""
        return f"Runbook match for '{query}': 1) Check logs 2) Restart service 3) Verify config"


# ---------------------------------------------------------------------------
# Custom Compaction Instructions
# ---------------------------------------------------------------------------

SUPPORT_COMPACTION_PROMPT = """
You are summarizing a support ticket conversation. Preserve ALL of:
- Ticket ID and error codes (exact strings)
- Software versions and configuration values
- Every troubleshooting step already attempted (so we don't re-suggest)
- User-stated constraints or preferences
- Current status and next steps

Format as a structured checkpoint the next agent can pick up immediately.
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="IT Support Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You help users troubleshoot IT issues.",
        "Always check service status before suggesting fixes.",
        "Track what has been tried to avoid repeating steps.",
    ],
    tools=[HelpdeskTools()],
    db=SqliteDb(db_file="tmp/support_agent.db"),
    add_history_to_context=True,
    # Context compaction with custom config
    compaction_manager=CompactionManager(
        compact_context=True,
        model=OpenAIResponses(id="gpt-5-mini"),
        compact_context_message_limit=30,  # Trigger by message count (support = many short turns)
        compact_context_keep_recent=8,  # Keep more recent context for support
        compact_context_preserve_user_budget=15_000,  # Keep user messages verbatim
        compact_context_instructions=SUPPORT_COMPACTION_PROMPT,  # Custom summarization prompt
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    session_id = "ticket-8841"

    # Turn 1: Initial report
    print("\n" + "=" * 60)
    print("TURN 1: Initial report")
    print("=" * 60 + "\n")

    agent.print_response(
        "Deploys to staging fail with ERR-4012 since this morning. Ticket TKT-8841.",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: Environment details
    print("\n" + "=" * 60)
    print("TURN 2: Environment details")
    print("=" * 60 + "\n")

    agent.print_response(
        "We're on deploy-service 3.2.1, config v14, EU cluster.",
        session_id=session_id,
        stream=True,
    )

    # Turn 3: Tried something
    print("\n" + "=" * 60)
    print("TURN 3: Tried restart")
    print("=" * 60 + "\n")

    agent.print_response(
        "Tried the runbook restart, no luck. What next?",
        session_id=session_id,
        stream=True,
    )

    # Turn 4: Next day follow-up
    print("\n" + "=" * 60)
    print("TURN 4: Next day (tests recall)")
    print("=" * 60 + "\n")

    response = agent.run(
        "Still failing after the cert rotation. Summarize where we are.",
        session_id=session_id,
    )
    print(response.content)

    # Show compaction stats
    print("\n" + "-" * 40)
    print("Compaction Stats")
    print("-" * 40)
    if response.compaction_state:
        print(f"  Total compactions: {response.compaction_state.total_compactions}")
        print(f"  Messages compacted: {response.compaction_state.compacted_count}")
        print(f"  Tokens saved: {response.compaction_state.total_tokens_saved}")
    else:
        print("  No compaction triggered (history within limits)")
