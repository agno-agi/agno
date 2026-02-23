# Cloud Knowledge Sources

This directory contains Agno knowledge cookbook examples for cloud storage providers.

Run an example with:

```bash
.venvs/demo/bin/python <path-to-example>.py
```

## GitHub (`github.py`)

Load files and folders from GitHub repositories into your Knowledge base.

### Option 1: Personal Access Token (PAT)

Best for individual use or simple setups.

1. Go to [GitHub Settings > Developer settings > Personal access tokens > Fine-grained tokens](https://github.com/settings/tokens?type=beta)
2. Click **Generate new token**
3. Set a name and expiration
4. Under **Repository access**, select the repos you need
5. Under **Permissions > Repository permissions**, set **Contents** to **Read-only**
6. Click **Generate token** and copy it

```bash
export GITHUB_TOKEN="github_pat_..."
```

### Option 2: GitHub App

Best for organizations or when you need scoped, rotatable credentials.

1. Go to [GitHub Settings > Developer settings > GitHub Apps](https://github.com/settings/apps) and click **New GitHub App**
2. Fill in the app name and homepage URL
3. Under **Repository permissions**, set **Contents** to **Read-only**
4. Uncheck **Webhook > Active** (not needed)
5. Click **Create GitHub App**

After creating the app:

- **App ID**: Shown on the app's **General** page
- **Private key**: On the **General** page, scroll to **Private keys** and click **Generate a private key** (downloads a `.pem` file)
- **Installation ID**: Click **Install App** in the sidebar, install it on your org/account, then find the ID in the URL: `github.com/settings/installations/<installation_id>`

```bash
export GITHUB_APP_ID="123456"
export GITHUB_INSTALLATION_ID="78901234"
export GITHUB_APP_PRIVATE_KEY="$(cat /path/to/your-app.private-key.pem)"
```

Requires optional dependencies:

```bash
pip install PyJWT cryptography
```
