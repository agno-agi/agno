# Google Tools Cookbooks

Build agents with Gmail, Google Calendar, Google Drive, and Google Slides. Supports OAuth (browser), service accounts (server), and multi-user interfaces.

## Which Cookbook?

| Need | Start Here |
|:-----|:-----------|
| Simple dev/testing | `gmail_tools.py`, `calendar_event_creator.py` |
| Persist tokens in DB | `google_workspace_with_db.py` |
| Multi-user (Slack/WhatsApp) | `slack/gmail_oauth.py` |
| Service account (no browser) | `google_service_account.py` |
| Restrict to company domain | `google_enterprise_oauth.py` |
| Multiple Google APIs | `google_workspace_agent.py` |

## What You'll Build

| File | What You'll Learn | Key Features |
|:-----|:------------------|:-------------|
| `gmail_tools.py` | Read and manage emails | Gmail API, Labels, Threads |
| `gmail_daily_digest.py` | Generate priority email digests | Structured Output, Classification |
| `gmail_inbox_triage.py` | Triage inbox with learning | LearningMachine, Personalization |
| `gmail_draft_reply.py` | Draft context-aware replies | Thread Context, Drafts |
| `gmail_with_db.py` | Persist Gmail tokens in DB | Token Storage, Multi-user |
| `calendar_event_creator.py` | Create calendar events | Events, Attendees, Google Meet |
| `calendar_daily_briefing.py` | Daily meeting summary | Conflict Detection, Prep Notes |
| `calendar_meeting_scheduler.py` | Find meeting availability | Free/Busy, Multi-person |
| `drive_tools.py` | Search and manage files | Upload, Download, Permissions |
| `drive_file_search.py` | Search with structured output | Pagination, Output Schema |
| `drive_document_reader.py` | Read Docs, Sheets, Slides | Content Extraction |
| `slide_tools.py` | Create presentations | Slides API, Layouts |
| `slides_presentation_builder.py` | Build multi-slide decks | Tables, Text, Images |
| `google_workspace_agent.py` | Multi-API agent (OAuth, file) | Scope Consolidation |
| `google_workspace_with_db.py` | Multi-API agent (OAuth, DB) | DB Token Storage |
| `google_service_account.py` | Server-side auth | Service Account, Delegation |
| `google_enterprise_oauth.py` | Restrict to company domain | `hosted_domain`, Enterprise |

## Key Concepts

| Concept | What It Does | When to Use |
|:--------|:-------------|:------------|
| **OAuth** | Browser-based user consent | Dev/testing, single-user apps |
| **Service Account** | Server-to-server auth | Bots, background jobs, enterprise |
| **GoogleAuthConfig** | Centralized auth config | Multi-toolkit agents, enterprise settings |
| **store_auth_tokens** | Persist tokens in DB | Multi-user apps, SaaS |
| **hosted_domain** | Restrict to Workspace domain | Enterprise security |

## Setup

1. Enable APIs at [Google Cloud Console](https://console.cloud.google.com)
2. Create OAuth credentials (Desktop app) or Service Account
3. Set environment variables:

```bash
# OAuth
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...

# Service Account
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json
export GOOGLE_DELEGATED_USER=user@domain.com
```
