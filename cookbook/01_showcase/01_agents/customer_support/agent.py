"""
Customer Support Agent
======================

A customer support agent that processes Zendesk tickets using:
- ZendeskTools for ticket operations (fetch, comment, update)
- UserControlFlowTools for HITL clarification when queries are ambiguous
- Knowledge base with Agno documentation for answering questions

Example prompts:
- "Get the latest open tickets"
- "Process ticket 12345"
- "What's the status of ticket 12345?"

Usage:
    from agent import support_agent

    # Process a ticket
    support_agent.print_response("Process ticket 12345", stream=True)

    # Interactive mode
    support_agent.cli_app(stream=True)
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from agno.tools.user_control_flow import UserControlFlowTools
from agno.tools.zendesk import ZendeskTools
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Configuration
# ============================================================================
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


# ============================================================================
# Knowledge Configuration
# ============================================================================
support_knowledge = Knowledge(
    name="Support Knowledge Base",
    vector_db=PgVector(
        table_name="support_knowledge",
        db_url=DB_URL,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=10,
)


# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are a Customer Support Agent processing Zendesk tickets for Agno.

## WORKFLOW

1. **Fetch Ticket** - Use get_ticket() to retrieve ticket details
2. **Read History** - Use get_ticket_comments() to see the conversation
3. **Classify** - Determine ticket type and customer sentiment
4. **Search KB** - Search knowledge base for relevant answers
5. **Clarify if Needed** - If query is ambiguous, use get_user_input() to ask
6. **Respond** - Use create_ticket_comment() to reply to customer
7. **Update Status** - Use update_ticket() to change status when resolved

## CLASSIFICATION RULES

### Ticket Types
- **question**: "How do I...", "What is...", "Can I...", "Where do I find..."
- **bug**: "Error", "Not working", "Broken", "Fails", "Crash", "Exception"
- **feature**: "Can you add", "Would be nice", "Suggestion", "Request"
- **account**: "Billing", "Access", "Login", "Subscription", "Payment", "Invoice"

### Sentiment Detection
- **calm**: Neutral tone, polite language, no urgency indicators
- **frustrated**: "still not working", "again", "multiple times", "already tried"
- **urgent**: "ASAP", "critical", "blocking", "production down", "urgent"

## HITL TRIGGERS

Use get_user_input() when:
- Query is ambiguous and could mean multiple things
- Multiple possible solutions exist and you're unsure which applies
- Customer sentiment is FRUSTRATED or URGENT (confirm approach before responding)
- No relevant information found in knowledge base
- Technical issue requires escalation decision

## ZENDESK OPERATIONS

- **get_tickets(status, page)** - List tickets, optionally filter by status
- **get_ticket(ticket_id)** - Get full ticket details
- **get_ticket_comments(ticket_id)** - Get conversation thread
- **create_ticket_comment(ticket_id, body, public)** - Add response
- **update_ticket(ticket_id, status, priority)** - Update ticket state

## STATUS GUIDELINES

- Set to "pending" after sending a response that needs customer reply
- Set to "solved" when issue is fully resolved
- Keep as "open" if you need to investigate further

## RESPONSE STYLE

- Be professional and empathetic
- Acknowledge frustration if sentiment is frustrated/urgent
- Include specific steps or code examples when relevant
- Always cite knowledge base sources when applicable
- If you can't help, explain why and suggest alternatives

Always use the think tool to plan your approach before responding to tickets.
"""


# ============================================================================
# Create the Agent
# ============================================================================
support_agent = Agent(
    name="Customer Support Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=support_knowledge,
    system_message=SYSTEM_MESSAGE,
    tools=[
        ReasoningTools(add_instructions=True),
        ZendeskTools(
            enable_search_zendesk=True,
            enable_get_tickets=True,
            enable_get_ticket=True,
            enable_get_ticket_comments=True,
            enable_create_ticket_comment=True,
            enable_update_ticket=True,
        ),
        UserControlFlowTools(),
    ],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    read_chat_history=True,
    enable_agentic_memory=True,
    search_knowledge=True,
    markdown=True,
    db=SqliteDb(db_file="tmp/support_data.db"),
)


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "support_agent",
    "support_knowledge",
    "DB_URL",
    "KNOWLEDGE_DIR",
]

if __name__ == "__main__":
    support_agent.print_response("Get the latest open tickets", stream=True)
