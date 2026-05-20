# Google Tools Cookbooks

Agents for Gmail, Google Calendar, Google Drive, and Google Slides using OAuth or service account authentication.

## Authentication Scenarios

| Scenario | Cookbook | Use Case |
|----------|----------|----------|
| **Interactive OAuth (file)** | `gmail_tools.py` | Dev/single-user: browser popup, saves `token.json` |
| **OAuth + DB Storage** | `google_workspace_with_db.py` | Persist tokens in DB, no browser each run |
| **Multi-user Interface** | `slack/gmail_oauth.py` | SaaS: Slack/WhatsApp bots with per-user OAuth |
| **Service Account** | `google_service_account.py` | Server/enterprise: no browser, domain-wide delegation |
| **Enterprise OAuth** | `google_enterprise_oauth.py` | Restrict to workspace domain (`hosted_domain`) |
| **Multi-toolkit** | `google_workspace_agent.py` | Gmail + Calendar + Drive with shared auth |

### Quick Decision Guide

```
Do you need per-user authentication?
├─ NO (single service account) → google_service_account.py
└─ YES
   ├─ Running in Slack/WhatsApp/Web interface? → slack/gmail_oauth.py
   ├─ Running standalone script?
   │  ├─ Want to persist tokens in DB? → google_workspace_with_db.py
   │  └─ OK with token.json file? → gmail_tools.py
   └─ Need to restrict to company domain? → google_enterprise_oauth.py
```

## Quick Start

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[GoogleCalendarTools()],
    add_datetime_to_context=True,
    markdown=True,
)

agent.print_response("What meetings do I have tomorrow?", stream=True)
```

### Multi-toolkit with DB Storage

```python
from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    db=SqliteDb(db_file="app.db", store_auth_tokens=True, encrypt_auth_tokens=False),
    tools=[
        GmailTools(),
        GoogleCalendarTools(),
    ],
)

agent.print_response("Show my emails and meetings", user_id="user-1")
```

### Service Account

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools

auth = GoogleAuthConfig(
    service_account_path="/path/to/key.json",
    delegated_user="admin@company.com",
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth_config=auth),  # First gets config, others inherit
        GoogleCalendarTools(),
    ],
)
```

### Enterprise OAuth (Domain Restriction)

```python
from agno.tools.google.auth import GoogleAuthConfig

auth = GoogleAuthConfig(hosted_domain="company.com")

agent = Agent(
    tools=[
        GoogleOAuthTools(auth_config=auth),
        GmailTools(),
    ],
)
```

## Setup

### 1. Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Note the **Project ID**

### 2. Enable APIs

Go to **APIs & Services > Enable APIs and Services** and enable:

| Toolkit | API to Enable |
|---------|--------------|
| `GoogleCalendarTools` | Google Calendar API |
| `GmailTools` | Gmail API |
| `GoogleDriveTools` | Google Drive API |
| `GoogleSlidesTools` | Google Slides API + Google Drive API |

### 3. Create OAuth Credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Complete the OAuth consent screen setup
4. Application type: **Desktop app**
5. Save the **Client ID** and **Client Secret**
6. Add your Google account to test users

### 4. Set Environment Variables

```bash
export GOOGLE_CLIENT_ID=your_client_id
export GOOGLE_CLIENT_SECRET=your_client_secret
export GOOGLE_PROJECT_ID=your_project_id
```

### 5. Install Dependencies

```bash
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

On first run, a browser window opens for OAuth consent.

### Service Account Setup

For server/bot deployments:

1. Create a service account at **IAM & Admin > Service Accounts**
2. Download the JSON key file
3. For Gmail, configure **domain-wide delegation** in Google Workspace Admin Console
4. Set environment variables:

```bash
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json
export GOOGLE_DELEGATED_USER=user@domain.com  # Required for Gmail
```

## Cookbooks

### Gmail

| File | Description |
|------|-------------|
| `gmail_tools.py` | Read-only agent, safe agent, label manager, full agent |
| `gmail_daily_digest.py` | Structured email digest with priority classification |
| `gmail_inbox_triage.py` | Personal inbox triage agent with LearningMachine |
| `gmail_draft_reply.py` | Thread-aware draft replies |
| `gmail_followup_tracker.py` | Find unanswered sent emails, draft follow-ups |
| `gmail_action_items.py` | Extract structured action items from email threads |
| `gmail_with_db.py` | Gmail with DB token storage |

### Calendar

| File | Description |
|------|-------------|
| `calendar_event_creator.py` | Event creation with attendees and Google Meet |
| `calendar_daily_briefing.py` | Daily briefing with conflict detection |
| `calendar_meeting_scheduler.py` | Multi-person scheduling with availability |

### Drive

| File | Description |
|------|-------------|
| `drive_tools.py` | Search, read, upload, and download files |
| `drive_file_search.py` | Search files with structured output |
| `drive_document_reader.py` | Read and summarize Docs, Sheets, Slides |
| `drive_folder_organizer.py` | Browse folders, upload/download files |

### Slides

| File | Description |
|------|-------------|
| `slide_tools.py` | Create presentation, add slides, read content |
| `slides_presentation_builder.py` | Multi-slide deck builder with tables |
| `slides_content_reader.py` | Read and summarize presentations |
| `slides_media_slides.py` | Background images, YouTube embeds |

### Combined/Auth

| File | Description |
|------|-------------|
| `google_workspace_agent.py` | Gmail + Calendar + Drive (OAuth, file) |
| `google_workspace_with_db.py` | Gmail + Calendar + Drive (OAuth, DB) |
| `google_service_account.py` | Service account with domain delegation |
| `google_enterprise_oauth.py` | OAuth with `hosted_domain` restriction |
| `calendar_gmail_meeting_prep.py` | Meeting prep with attendee email context |
