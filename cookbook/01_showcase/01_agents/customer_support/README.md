# Customer Support Agent

A customer support agent that resolves tickets using knowledge base retrieval, handles common inquiries autonomously, and escalates complex issues appropriately.

## Features

- **Ticket Classification**: Automatically categorizes tickets by type, priority, and sentiment
- **Sentiment Detection**: Detects customer emotion and adjusts response tone accordingly
- **Smart Escalation**: Identifies tickets that need human intervention based on configurable criteria
- **Response Generation**: Crafts empathetic, accurate responses tailored to the situation
- **Knowledge Base (RAG)**: LanceDB-powered knowledge base with support manual and procedures
- **Linear Integration**: Create and track support tickets
- **Zendesk Integration**: Search help center articles
- **Slack Integration**: Send notifications and updates
- **Security Guardrails**: PII detection, prompt injection protection, and content moderation

## Installation

```bash
pip install -r requirements.in
```

## Prerequisites

### Required

The agent uses **GPT-5-mini** by default. You can also use **Claude Opus 4.5** as an alternative.

**For GPT-5-mini (Default):**

```bash
# Windows
set OPENAI_API_KEY=your-api-key

# Unix/Mac
export OPENAI_API_KEY=your-api-key
```

**For Gemini 2.5 Flash Lite (Alternative):**

```bash
# Windows
set GOOGLE_API_KEY=your-api-key

# Unix/Mac
export GOOGLE_API_KEY=your-api-key
```

**For Claude Haiku 4.5 (Alternative):**

```bash
# Windows
set ANTHROPIC_API_KEY=your-api-key

# Unix/Mac
export ANTHROPIC_API_KEY=your-api-key
```

### Optional (Tool Integrations)

**Linear (Ticket Management):**

```bash
export LINEAR_API_KEY=your-linear-api-key
```

Get your API key at: https://linear.app/settings/api

**Zendesk (Knowledge Base):**

```bash
export ZENDESK_SUBDOMAIN=your-subdomain
export ZENDESK_EMAIL=your-email
export ZENDESK_TOKEN=your-api-token
```

Get your API token at: https://your-subdomain.zendesk.com/admin/apps-integrations/apis/zendesk-api

**Slack (Notifications):**

```bash
export SLACK_BOT_TOKEN=xoxb-your-bot-token
```

Create a Slack app at: https://api.slack.com/apps

## Quick Start

### Verify Setup

```bash
python scripts/check_setup.py
```

### Interactive CLI

```bash
python agent.py
```

### Run Examples

```bash
python examples/run_examples.py
```

This launches a menu-based TUI with the following options:

```
  1. Billing Issue (Duplicate Charge)
  2. Technical Issue (Service Unavailable)
  3. Account Issue (Password Reset)
  4. Angry Customer (Shipping Delay + Escalation)
  5. Product Inquiry (Plan Upgrade)
  6. Interactive Mode

  0. Exit
```

## Usage

### Command Line Interface

```bash
python agent.py
```

This starts an interactive session where you can paste support tickets or describe customer issues.

### Python API

```python
from agent import customer_support_agent

# Handle a support ticket
customer_support_agent.print_response(
    "Customer says: I was charged twice for my subscription. Order #12345.",
    stream=True,
)

# Handle an angry customer
customer_support_agent.print_response(
    "Customer is threatening to cancel and post on social media about a "
    "shipping delay. Order hasn't arrived in 3 weeks.",
    stream=True,
)
```

## Database

This agent uses [SQLite](https://docs.agno.com/database/providers/sqlite/overview) for session storage during development. For production, switch to [PostgreSQL](https://docs.agno.com/database/providers/postgres/overview):

```python
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
```

See [Session Storage](https://docs.agno.com/database/session-storage) for more details.

## Security Guardrails

The agent includes pre-processing guardrails:

| Guardrail | Purpose |
|-----------|---------|
| `PIIDetectionGuardrail` | Detects PII (SSN, credit cards, emails, etc.) |
| `PromptInjectionGuardrail` | Prevents prompt injection attacks |
| `OpenAIModerationGuardrail` | Filters inappropriate/harmful content |

## Tools Used

| Tool | Purpose | Docs |
|------|---------|------|
| [`WebSearchTools`](https://docs.agno.com/tools/toolkits/search/websearch) | Search for solutions, known issues, and product info | [Web Search](https://docs.agno.com/tools/toolkits/search/websearch) |
| [`LinearTools`](https://docs.agno.com/tools/toolkits/others/linear) | Create and manage support tickets in Linear | [Linear](https://docs.agno.com/tools/toolkits/others/linear) |
| [`ZendeskTools`](https://docs.agno.com/tools/toolkits/others/zendesk) | Search knowledge base articles in Zendesk Help Center | [Zendesk](https://docs.agno.com/tools/toolkits/others/zendesk) |
| [`SlackTools`](https://docs.agno.com/tools/toolkits/social/slack) | Send notifications and updates to Slack channels | [Slack](https://docs.agno.com/tools/toolkits/social/slack) |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes (default) | OpenAI API key for GPT-5-mini model and embeddings |
| `GOOGLE_API_KEY` | Optional | Google API key for Gemini 2.5 Flash Lite |
| `ANTHROPIC_API_KEY` | Optional | Anthropic API key for Claude Haiku 4.5 |
| `LINEAR_API_KEY` | Optional | Linear API key for ticket management |
| `ZENDESK_SUBDOMAIN` | Optional | Your Zendesk subdomain |
| `ZENDESK_EMAIL` | Optional | Zendesk account email |
| `ZENDESK_TOKEN` | Optional | Zendesk API token |
| `SLACK_BOT_TOKEN` | Optional | Slack bot token for notifications |

## Project Structure

```
customer_support/
├── agent.py              # Main agent definition
├── __init__.py           # Package exports
├── requirements.in       # Dependencies
├── README.md             # This file
├── manual/
│   └── support_manual.txt  # Knowledge base with FAQs and procedures
├── scripts/
│   └── check_setup.py    # Setup verification
└── examples/
    └── run_examples.py   # Menu-based TUI with sample tickets
```

## Agno Documentation

- [Agents](https://docs.agno.com/agents/introduction) - Core agent concepts
- [OpenAI Models](https://docs.agno.com/models/providers/native/openai/overview) - GPT-5-mini and other OpenAI models
- [Google Gemini Models](https://docs.agno.com/models/providers/native/google/overview) - Gemini 2.5 Flash Lite
- [Anthropic Models](https://docs.agno.com/models/providers/native/anthropic/overview) - Claude Haiku 4.5
- [Knowledge (RAG)](https://docs.agno.com/knowledge/agents/overview) - Knowledge base integration
- [LanceDB](https://docs.agno.com/knowledge/vector-stores/lancedb/overview) - Vector database for knowledge
- [Session Storage](https://docs.agno.com/database/session-storage) - Persisting agent sessions
- [SQLite Storage](https://docs.agno.com/database/providers/sqlite/overview) - SQLite for development
- [PostgreSQL Storage](https://docs.agno.com/database/providers/postgres/overview) - PostgreSQL for production
- [Tools Overview](https://docs.agno.com/tools/overview) - Available toolkits
- [MCP Integration](https://docs.agno.com/tools/mcp/overview) - Model Context Protocol tools

## License

See the main Agno repository license.
