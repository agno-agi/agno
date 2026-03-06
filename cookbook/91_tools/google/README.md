# Google Tools Cookbooks

## Setup

### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Note the **Project ID** from the project dropdown

### 2. Enable APIs

Go to **APIs & Services > Enable APIs and Services** and enable the APIs you need:

| Toolkit | API to Enable |
|---------|--------------|
| Gmail | Gmail API |

### 3. Create OAuth Credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Complete the OAuth consent screen setup
4. Application type: **Desktop app** (for local development)
5. Save the **Client ID** and **Client Secret**

### 4. Set Environment Variables

```bash
export GOOGLE_CLIENT_ID=your_client_id
export GOOGLE_CLIENT_SECRET=your_client_secret
export GOOGLE_PROJECT_ID=your_project_id
export GOOGLE_REDIRECT_URI=http://127.0.0.1/  # default
```

### 5. Install Dependencies

```bash
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

On first run, a browser window opens for OAuth consent. A `token.json` file is saved for subsequent runs.

### Service Account Authentication (Alternative)

For server/bot deployments with no browser:

1. Create a service account at **IAM & Admin > Service Accounts**
2. Download the JSON key file
3. If accessing user data (e.g. Gmail), configure **domain-wide delegation** in Google Workspace Admin Console
4. Set environment variables:

```bash
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account-key.json
export GOOGLE_DELEGATED_USER=user@yourdomain.com  # required for Gmail
```

## Cookbooks

| File | Description |
|------|-------------|
| `gmail_tools.py` | Core examples: read-only agent, safe agent, label manager, full agent, thread reply |
| `gmail_daily_digest.py` | Structured email digest with priority classification |
| `gmail_inbox_triage.py` | Personal inbox triage agent with LearningMachine |
| `gmail_draft_reply.py` | Thread-aware draft replies |
| `gmail_followup_tracker.py` | Find unanswered sent emails, draft follow-ups |
| `gmail_action_items.py` | Extract structured action items from email threads |

### Running

```bash
.venvs/demo/bin/python cookbook/91_tools/google/gmail_tools.py
```
