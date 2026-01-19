# Inbox Agent

An intelligent email assistant that connects to Gmail, triages incoming messages, summarizes important emails, drafts responses, and helps manage inbox zero.

## Quick Start

### 1. Prerequisites

Set up Google OAuth credentials:

```bash
# Set Google OAuth credentials
export GOOGLE_CLIENT_ID=your-client-id
export GOOGLE_CLIENT_SECRET=your-client-secret
export GOOGLE_PROJECT_ID=your-project-id
export GOOGLE_REDIRECT_URI=http://127.0.0.1/

# Set OpenAI API key
export OPENAI_API_KEY=your-openai-api-key
```

### 2. Get Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing
3. Enable the Gmail API:
   - Go to "APIs & Services" > "Enable APIs and Services"
   - Search for "Gmail API" and enable it
4. Create OAuth credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Select "Desktop app" as application type
   - Download the credentials
5. Add redirect URI:
   - Go to OAuth consent screen settings
   - Add `http://127.0.0.1/` as authorized redirect URI

### 3. Run Examples

```bash
# Triage inbox
.venvs/demo/bin/python cookbook/01_showcase/01_agents/inbox_agent/examples/01_triage_inbox.py

# Summarize email thread
.venvs/demo/bin/python cookbook/01_showcase/01_agents/inbox_agent/examples/02_summarize_thread.py

# Draft a response
.venvs/demo/bin/python cookbook/01_showcase/01_agents/inbox_agent/examples/03_draft_response.py
```

Note: First run will open a browser window for OAuth authentication.

## Key Concepts

### Email Categories

The agent categorizes emails into:

| Category | Criteria | Default Action |
|----------|----------|----------------|
| **urgent** | Time-sensitive, VIPs, deadlines | Surface immediately |
| **action_required** | Requests, questions | Queue for response |
| **fyi** | Updates, notifications, CC'd | Summarize briefly |
| **newsletter** | Marketing, subscriptions | Archive or summarize |
| **spam** | Unwanted promotional | Archive |

### Priority Levels

| Level | Description | Timeframe |
|-------|-------------|-----------|
| 1 | Critical | Immediate |
| 2 | High | 24-48 hours |
| 3 | Medium | Within a week |
| 4 | Low | Informational |
| 5 | Minimal | Archive/skip |

### Gmail Tools

The agent uses these Gmail operations:

| Tool | Description |
|------|-------------|
| `get_unread_emails` | Retrieve unread messages |
| `get_emails_by_thread` | Get full thread |
| `search_emails` | Search by query |
| `create_draft_email` | Save draft (no send) |
| `send_email_reply` | Reply to thread |
| `apply_label` | Organize with labels |
| `mark_email_as_read` | Mark processed |

## Architecture

```
User Command
    |
    v
[Inbox Agent (GPT-5.2)]
    |
    +---> GmailTools
    |         |
    |         +---> get_unread_emails
    |         +---> get_emails_by_thread
    |         +---> search_emails
    |         +---> create_draft_email
    |         +---> apply_label
    |
    +---> ReasoningTools ---> think/analyze
    |
    +---> Agentic Memory (contacts, preferences)
    |
    v
Triage Report / Thread Summary / Draft
```

## Safety Features

The agent includes safety measures:

1. **No auto-send**: Emails are saved as drafts, never auto-sent
2. **Confirmation required**: Sending requires explicit user approval
3. **Read-only default**: Only reads emails unless action requested
4. **Phishing detection**: Warns about suspicious emails

## Usage Examples

### Triage Inbox

```python
from agent import inbox_agent

inbox_agent.print_response(
    "Triage my 10 most recent unread emails",
    stream=True
)
```

### Summarize Thread

```python
inbox_agent.print_response(
    "Find the email thread about the Q4 planning and summarize it",
    stream=True
)
```

### Draft Response

```python
inbox_agent.print_response(
    "Draft a response to John's email about the budget proposal",
    stream=True
)
```

## OAuth Token Storage

After first authentication, a `token.json` file is created to store credentials. This allows subsequent runs without re-authentication.

To reset authentication:
```bash
rm token.json
```

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model
- `google-api-python-client` - Gmail API
- `google-auth-oauthlib` - OAuth authentication

## API Credentials

To use this agent, you need:

1. **OpenAI API key** for GPT-5.2
2. **Google OAuth credentials** for Gmail access

See the Prerequisites section for setup instructions.
