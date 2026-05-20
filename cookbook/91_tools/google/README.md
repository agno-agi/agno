# Google Tools Cookbooks

Gmail, Calendar, Drive, and Slides agents with OAuth or service account auth.

## Which Cookbook?

| Need | Cookbook |
|------|----------|
| Simple dev/testing | `gmail_tools.py`, `calendar_event_creator.py` |
| Persist tokens in DB | `google_workspace_with_db.py` |
| Multi-user (Slack/WhatsApp) | `slack/gmail_oauth.py` |
| Service account (no browser) | `google_service_account.py` |
| Restrict to company domain | `google_enterprise_oauth.py` |
| Multiple Google APIs | `google_workspace_agent.py` |

## Setup

1. Enable APIs at [Google Cloud Console](https://console.cloud.google.com)
2. Create OAuth credentials (Desktop app)
3. Set env vars:

```bash
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...
```

For service accounts:
```bash
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json
export GOOGLE_DELEGATED_USER=user@domain.com  # Gmail only
```

## Cookbooks

### Gmail
- `gmail_tools.py` — Basic read/write
- `gmail_daily_digest.py` — Priority digest
- `gmail_inbox_triage.py` — Triage with learning
- `gmail_draft_reply.py` — Thread-aware drafts
- `gmail_with_db.py` — DB token storage

### Calendar
- `calendar_event_creator.py` — Create events
- `calendar_daily_briefing.py` — Daily summary
- `calendar_meeting_scheduler.py` — Find availability

### Drive
- `drive_tools.py` — Search/read/upload
- `drive_file_search.py` — Structured search
- `drive_document_reader.py` — Read docs

### Slides
- `slide_tools.py` — Create/edit slides
- `slides_presentation_builder.py` — Build decks

### Auth
- `google_workspace_agent.py` — Multi-API, file tokens
- `google_workspace_with_db.py` — Multi-API, DB tokens
- `google_service_account.py` — Service account
- `google_enterprise_oauth.py` — Domain restriction
