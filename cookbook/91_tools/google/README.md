# Google Tools Cookbooks

Agents for Gmail, Google Calendar, Google Drive, and Google Slides using OAuth or service account authentication.

## Quick Start

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.calendar import GoogleCalendarTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleCalendarTools()],
    add_datetime_to_context=True,
    markdown=True,
)

agent.print_response("What meetings do I have tomorrow?", stream=True)
```

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.slides import GoogleSlidesTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleSlidesTools()],
    markdown=True,
)

agent.print_response("Create a presentation titled 'Q3 Review'", stream=True)
```

## Setup

### 1. Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Note the **Project ID** from the project dropdown

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
6. Go to **APIs & Services > OAuth consent screen > Test users** and add your Google account

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

On first run, a browser window opens for OAuth consent. A `token.json` file is saved for subsequent runs.

### Service Account Authentication

For server/bot deployments with no browser:

1. Create a service account at **IAM & Admin > Service Accounts**
2. Download the JSON key file
3. For Gmail or accessing another user's calendar, configure **domain-wide delegation** in Google Workspace Admin Console
4. Set environment variables:

```bash
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account-key.json
export GOOGLE_DELEGATED_USER=user@yourdomain.com  # required for Gmail, optional for Calendar/Slides
```

## Cookbooks

### Gmail

| File | Description |
|------|-------------|
| `gmail_tools.py` | Core examples: read-only agent, safe agent, label manager, full agent, thread reply |
| `gmail_daily_digest.py` | Structured email digest with priority classification |
| `gmail_inbox_triage.py` | Personal inbox triage agent with LearningMachine |
| `gmail_draft_reply.py` | Thread-aware draft replies |
| `gmail_followup_tracker.py` | Find unanswered sent emails, draft follow-ups |
| `gmail_action_items.py` | Extract structured action items from email threads |

### Calendar

| File | Description |
|------|-------------|
| `calendar_event_creator.py` | Event creation with attendees, Google Meet, and timezone handling |
| `calendar_daily_briefing.py` | Structured daily briefing with conflict detection and prep notes |
| `calendar_meeting_scheduler.py` | Multi-person scheduling with availability checking |

### Drive

| File | Description |
|------|-------------|
| `drive_tools.py` | Read-only and full-access agents: search, read, upload, and download files |
| `drive_file_search.py` | Search files with structured output schema and pagination |
| `drive_document_reader.py` | Read and summarize Google Docs, Sheets, and Slides as text |
| `drive_folder_organizer.py` | Browse folder structure, upload local files, and download from Drive |

### Slides

| File | Description |
|------|-------------|
| `slide_tools.py` | Core examples: create presentation, add slides, read content, list, delete |
| `slides_presentation_builder.py` | Multi-slide deck builder with tables, layouts, and text annotations |
| `slides_content_reader.py` | Read and summarize existing presentations with structured output |
| `slides_media_slides.py` | Background images, YouTube embeds, and Drive video integration |

### Combined

| File | Description |
|------|-------------|
| `calendar_gmail_meeting_prep.py` | Calendar + Gmail: meeting prep briefs with attendee email context |
