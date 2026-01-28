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

## Tools Used

| Tool | Purpose |
|------|---------|
| `WebSearchTools` | Search for solutions, known issues, and product info |
| `LinearTools` | Create and manage support tickets in Linear |
| `ZendeskTools` | Search knowledge base articles in Zendesk Help Center |
| `SlackTools` | Send notifications and updates to Slack channels |

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

## License

See the main Agno repository license.
