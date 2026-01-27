# Customer Support Agent

A production-ready customer support agent that processes Zendesk tickets using knowledge-based responses and native Human-in-the-Loop (HITL) for complex cases.

## What Makes This Different

| Feature | Description |
|---------|-------------|
| **Zendesk Integration** | Full ticket CRUD - fetch, comment, update status |
| **Production Knowledge Base** | Ticket triage, escalation guidelines, SLA policies, response templates |
| **Ticket Classification** | Automatic type (bug/question/feature/account) and sentiment detection |
| **Native HITL** | `get_user_input()` for clarification when queries are ambiguous |
| **Empathy-Aware Responses** | Different response styles for calm, frustrated, and urgent customers |

## Quick Start

### 1. Prerequisites

```bash
# Set OpenAI API key (for model and embeddings)
export OPENAI_API_KEY=your-openai-api-key

# Set Zendesk credentials (optional - for live ticket integration)
export ZENDESK_USERNAME=your-email
export ZENDESK_PASSWORD=your-api-token
export ZENDESK_COMPANY_NAME=your-subdomain

# Start PostgreSQL with PgVector
./cookbook/scripts/run_pgvector.sh
```

### 2. Load Knowledge Base

```bash
# Load support documentation and Agno docs
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/scripts/load_knowledge.py
```

### 3. Run Examples

```bash
# Basic support workflow
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/basic_support.py

# HITL clarification demo
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/hitl_clarification.py

# Triage queue processing
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/triage_queue.py

# Interactive mode
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/basic_support.py --interactive
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Customer Support Agent                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ZENDESK TOOLS                  KNOWLEDGE BASE              │
│  ┌─────────────┐               ┌─────────────────────┐      │
│  │ get_tickets │               │ Ticket Triage       │      │
│  │ get_ticket  │               │ Escalation Rules    │      │
│  │ get_comments│               │ Response Templates  │      │
│  │ add_comment │               │ SLA Guidelines      │      │
│  │ update      │               │ Agno Docs           │      │
│  └─────────────┘               └─────────────────────┘      │
│        │                              │                     │
│        └──────────────┬───────────────┘                     │
│                       ▼                                     │
│         ┌─────────────────────────┐                         │
│         │    SUPPORT AGENT        │                         │
│         │  ┌───────────────────┐  │                         │
│         │  │ 1. Fetch ticket   │  │                         │
│         │  │ 2. Classify type  │  │                         │
│         │  │ 3. Detect sentiment│ │                         │
│         │  │ 4. Search KB      │  │                         │
│         │  │ 5. HITL if needed │  │                         │
│         │  │ 6. Generate reply │  │                         │
│         │  │ 7. Update status  │  │                         │
│         │  └───────────────────┘  │                         │
│         └─────────────────────────┘                         │
│                       │                                     │
│                       ▼                                     │
│         ┌─────────────────────────┐                         │
│         │  UserControlFlowTools   │                         │
│         │  get_user_input()       │                         │
│         │  (HITL clarification)   │                         │
│         └─────────────────────────┘                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Classification System

### Ticket Types

| Type | Keywords | Example |
|------|----------|---------|
| **Question** | how do I, what is, can I | "How do I set up a knowledge base?" |
| **Bug** | error, not working, crash | "Agent crashes when adding tools" |
| **Feature** | can you add, suggestion | "Would be nice to have Slack integration" |
| **Account** | billing, access, login | "Can't access my dashboard" |

### Sentiment Detection

| Sentiment | Indicators | Response Style |
|-----------|------------|----------------|
| **Calm** | Neutral tone, polite | Standard professional |
| **Frustrated** | "still", "again", "third time" | Empathetic, acknowledge history |
| **Urgent** | "ASAP", "production down" | Immediate, expedited |

### Priority Mapping

| Priority | Response Time | Triggers |
|----------|---------------|----------|
| P1 - Critical | 15 min | Production down, security |
| P2 - High | 1 hour | Major feature broken |
| P3 - Medium | 4 hours | Partial issues, workaround available |
| P4 - Low | 1 day | Questions, feature requests |

## HITL (Human-in-the-Loop)

The agent uses `UserControlFlowTools.get_user_input()` to pause and request clarification when:

1. **Ambiguous queries** - "Search isn't working" (which search?)
2. **Missing information** - No error message or steps provided
3. **Escalation decisions** - VIP customer, repeated issue
4. **Low confidence** - Multiple possible solutions

```python
# The agent will pause here if clarification needed
response = support_agent.run("Customer says: It's not working")

# Check if HITL was triggered
if response.tool_calls:
    for tc in response.tool_calls:
        if tc.function.name == "get_user_input":
            # Agent is waiting for input
            print("Agent needs clarification:", tc.function.arguments)
```

## Knowledge Base Contents

| Document | Description |
|----------|-------------|
| `ticket_triage.md` | Priority classification, triage workflow |
| `escalation_guidelines.md` | Tier structure, when to escalate |
| `response_templates.md` | Empathy statements, response structures |
| `sla_guidelines.md` | Response times, breach prevention |
| Agno Docs | Product documentation from docs.agno.com |

## Zendesk Integration

The agent has full Zendesk ticket management capabilities:

```python
from agno.tools.zendesk import ZendeskTools

zendesk = ZendeskTools(
    enable_get_tickets=True,      # List tickets
    enable_get_ticket=True,       # Get ticket details
    enable_get_ticket_comments=True,  # Get conversation
    enable_create_ticket_comment=True, # Add response
    enable_update_ticket=True,    # Change status/priority
)
```

Without Zendesk credentials, the agent still works with simulated ticket scenarios.

## Example Prompts

```
# Process a specific ticket
"Get ticket 12345 and draft a response"

# Triage the queue
"Show me all open tickets and prioritize them"

# Handle frustrated customer
"Customer is frustrated about repeated issues with knowledge search"

# Technical support
"Customer asks: How do I configure hybrid search with PgVector?"
```

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model and embeddings
- `psycopg[binary]` - PostgreSQL driver
- `pgvector` - Vector extension
- `requests` - Zendesk API

## API Credentials

### Required
- **OPENAI_API_KEY** - For model and embeddings

### Optional (for live Zendesk)
- **ZENDESK_USERNAME** - Your Zendesk email
- **ZENDESK_PASSWORD** - API token (not password)
- **ZENDESK_COMPANY_NAME** - Your subdomain (e.g., "mycompany" for mycompany.zendesk.com)

## Resources

- [Ticket Triage Best Practices](https://www.chatbees.ai/blog/ticket-triage)
- [Escalation Management](https://hiverhq.com/blog/escalation-management)
- [Empathy Statements](https://blog.hubspot.com/service/empathy-phrases-customer-service)
- [SLA Guidelines](https://www.freshworks.com/itsm/sla/response-time/)
