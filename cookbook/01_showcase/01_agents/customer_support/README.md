# Customer Support Agent

A production-ready customer support agent that processes support tickets using knowledge-based responses, automatic classification, and native Human-in-the-Loop (HITL) for complex cases.

## What Makes This Different

| Feature | Description |
|---------|-------------|
| **Knowledge-First Responses** | Always searches KB before responding; cites sources in answers |
| **Automatic Classification** | Classifies ticket type (bug/question/feature/account) and sentiment |
| **Escalation Policy** | Strict rules for security, billing, VIP, and repeat issues |
| **Native HITL** | Uses `get_user_input()` when queries are ambiguous |
| **Zendesk Integration** | Full ticket CRUD operations (optional) |

## Structure

This cookbook is organized into two levels:

```
customer_support/
├── basic/                 # Start here - core concepts
│   ├── agent.py           # Simplified agent (Knowledge + Zendesk + Reasoning)
│   ├── simple_query.py    # Basic support workflow
│   └── knowledge_reply.py # RAG with citations
│
├── advanced/              # Production patterns
│   ├── agent.py           # Full agent (+ HITL + Memory + Escalation)
│   ├── triage_queue.py    # Priority-based processing
│   ├── escalation_policy.py # Escalation rules
│   ├── hitl_demo.py       # Human-in-the-loop
│   └── evaluate.py        # Testing
│
├── knowledge/             # Shared KB documents
└── scripts/               # Setup utilities
```

## What You'll Learn

| Level | Example | Concept |
|-------|---------|---------|
| Basic | `simple_query.py` | Ticket classification, KB search, response generation |
| Basic | `knowledge_reply.py` | RAG pattern with explicit source citations |
| Advanced | `triage_queue.py` | Processing multiple tickets by priority |
| Advanced | `escalation_policy.py` | When and how to escalate (security, billing, VIP) |
| Advanced | `hitl_demo.py` | Pausing for human input on ambiguous queries |
| Advanced | `evaluate.py` | Testing agent responses with keyword matching |

## Quick Start

### 1. Set API Keys

```bash
# Required
export OPENAI_API_KEY=your-openai-api-key

# Optional (for live Zendesk integration)
export ZENDESK_USERNAME=your-email/token
export ZENDESK_PASSWORD=your-api-token
export ZENDESK_COMPANY_NAME=your-subdomain
```

### 2. Start PostgreSQL

```bash
./cookbook/scripts/run_pgvector.sh
```

### 3. Check Setup

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/scripts/check_setup.py
```

### 4. Load Knowledge Base

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/scripts/load_knowledge.py
```

### 5. Run Examples

**Start with basic examples:**

```bash
# Basic support workflow
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/basic/simple_query.py

# Knowledge-first with citations
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/basic/knowledge_reply.py

# Interactive mode
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/basic/simple_query.py --interactive
```

**Then explore advanced patterns:**

```bash
# Ticket triage queue
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/advanced/triage_queue.py

# Escalation scenarios
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/advanced/escalation_policy.py

# HITL clarification
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/advanced/hitl_demo.py

# Run evaluation
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/advanced/evaluate.py
```

## Key Concepts

### Basic vs Advanced Agent

| Feature | Basic | Advanced |
|---------|-------|----------|
| Knowledge base | Yes | Yes |
| ZendeskTools | Yes | Yes |
| ReasoningTools | Yes | Yes |
| UserControlFlowTools (HITL) | No | Yes |
| Agentic memory | No | Yes |
| Chat history | No | Yes |
| Full system message | No | Yes |

### Knowledge-First Responses

The agent always searches the knowledge base before responding:

```python
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,  # Auto-search on every query
    ...
)
```

Knowledge base contains:
- `ticket_triage.md` - Priority classification workflow
- `escalation_guidelines.md` - When to escalate and to whom
- `response_templates.md` - Empathy statements and response structures
- `sla_guidelines.md` - Response time targets by priority

### Ticket Classification

```
Query Analysis
     |
     v
+----+----+     +-----------+     +----------+
| Type    | --> | Sentiment | --> | Priority |
+---------+     +-----------+     +----------+
| question|     | calm      |     | P4 - Low |
| bug     |     | frustrated|     | P3 - Med |
| feature |     | urgent    |     | P2 - High|
| account |     |           |     | P1 - Crit|
+---------+     +-----------+     +----------+
```

### Escalation Workflow

```
Ticket Received
      |
      v
+-----+-----+
| Security? | --> Yes --> Security Team (immediate)
+-----+-----+
      | No
      v
+-----+-----+
| Billing?  | --> Yes --> Finance Team
+-----+-----+
      | No
      v
+-----+-----+
| VIP/Ent?  | --> Yes --> P1 Priority, Senior Engineer
+-----+-----+
      | No
      v
+-----+-----+
| Repeat?   | --> Yes --> Manager Escalation
+-----+-----+
      | No
      v
Standard Support Flow
```

### Native HITL

The agent uses `UserControlFlowTools.get_user_input()` when:
- Query is ambiguous (could mean multiple things)
- Multiple solutions exist (unsure which applies)
- Customer is frustrated/urgent (confirm approach)
- No KB match found (need human guidance)

```python
# HITL triggers automatically when needed
response = agent.run("Search isn't working")
# Agent may pause: "Which search: KB, web, or vector?"
```

## Example Prompts

**Simple Questions:**
```
How do I set up hybrid search with PgVector?
What are the response time targets for P1 tickets?
When should I escalate to Tier 2?
```

**Ticket Processing:**
```
Process ticket 12345 and draft a response
Show me all open tickets and prioritize them
Customer says: The agent keeps crashing when I add tools
```

**Escalation Triggers:**
```
Customer reports unauthorized access to their account
Customer is FURIOUS about repeated billing errors
VIP enterprise customer with production down
```

## Troubleshooting

### PostgreSQL Connection Failed

```
[FAIL] Cannot connect to PostgreSQL
```

**Solution:** Start the PostgreSQL container:
```bash
./cookbook/scripts/run_pgvector.sh
```

### Knowledge Base Empty

```
[WARN] Knowledge base empty (0 documents)
```

**Solution:** Load the knowledge documents:
```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/scripts/load_knowledge.py
```

### Zendesk Credentials Missing

```
WARNING  Zendesk credentials not provided
```

**Solution:** This is optional. Examples work with simulated tickets. For live Zendesk:
```bash
export ZENDESK_USERNAME=your-email/token
export ZENDESK_PASSWORD=your-api-token
export ZENDESK_COMPANY_NAME=your-subdomain
```

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model and embeddings
- `psycopg[binary]` - PostgreSQL driver
- `pgvector` - Vector extension
- `requests` - Zendesk API

## Learn More

- [Agno Knowledge Documentation](https://docs.agno.com/agents/knowledge)
- [Agno Tools Documentation](https://docs.agno.com/agents/tools)
- [PgVector Setup Guide](https://docs.agno.com/vectordb/pgvector)
