# GitHub

The `GitHub` interface receives a GitHub App's webhook deliveries for the
repositories you choose and hands each verified event to a handler. Unlike chat
interfaces, it is not bound to an agent: the handler decides what an event
becomes, for example a Company Task.

What the interface does before calling the handler:

- Refuses deliveries without a valid `X-Hub-Signature-256` signature for the
  webhook's secret (400 when missing, 403 when wrong).
- Answers GitHub's `ping`.
- Ignores, with a 200 and a reason: repositories it does not watch, events it
  does not handle (default `issues.opened` and `issue_comment.created`), bots
  (including the App's own `[bot]` account), the logins in `ignore_logins`, and
  text carrying Agno's own marker.
- Passes the installation that sent the delivery as `event.installation_id`,
  so the handler can act with that installation's token.

The handler must record the event before it returns. GitHub does not retry a
failed delivery on its own, so the interface reports success (202) only after
the handler returns, and a handler error returns 500 so the delivery can be
redelivered from the App's **Advanced** settings.

`agno.utils.github_auth.GitHubAppCredentials` mints the installation tokens: it
signs a short-lived JWT with the App's private key and exchanges it for a token
valid for an hour, cached per installation. Uninstalling the App, or removing a
repository from it, revokes that access.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Serve the interface for one repository and read each new issue back with the App's installation token; `--check` sends signed deliveries in process. |

## Prerequisites

```bash
./scripts/demo_setup.sh
```

`--check` needs nothing else. Serving for a real repository needs ngrok
(`brew install ngrok`) and a GitHub App, set up below.

## Set up a GitHub App on a private repository

1. **Start ngrok** and copy the `https://….ngrok-free.app` forwarding URL it
   prints. The App's webhook points there.

   ```bash
   ngrok http 7777
   ```

2. **Generate the webhook secret** once, so every terminal uses the same value:

   ```bash
   openssl rand -hex 32 > ~/.agno_github_webhook_secret
   ```

3. **Create the App**: GitHub → **Settings** → **Developer settings** →
   **GitHub Apps** → **New GitHub App** (for an organization: the organization's
   **Settings** → **Developer settings** → **GitHub Apps**).

   | Field | Value |
   |---|---|
   | GitHub App name | Any unique name, e.g. `<you>-agno-dev` |
   | Homepage URL | Any URL, e.g. your repository's |
   | Webhook → Active | Checked |
   | Webhook URL | `<ngrok URL>/github/events` |
   | Webhook secret | The contents of `~/.agno_github_webhook_secret` |
   | Repository permissions | **Issues**: Read and write; **Contents**: Read-only; **Metadata**: Read-only |
   | Subscribe to events | **Issues**, **Issue comment** |
   | Where can this GitHub App be installed? | **Only on this account** |

   Leave every other permission at **No access**.

4. **Note the App ID** at the top of the App's **General** page, then under
   **Private keys** click **Generate a private key**. GitHub downloads a `.pem`
   file; keep it outside the repository.

5. **Install the App**: on the App's page, **Install App** → your account →
   **Only select repositories** → your private repository → **Install**.

6. **Remove any repository webhook** you created earlier for the same events, or
   each event arrives twice:

   ```bash
   gh api repos/<owner>/<repo>/hooks --jq '.[] | "\(.id) \(.config.url)"'
   gh api -X DELETE repos/<owner>/<repo>/hooks/<id>
   ```

## Run

```bash
# Local check, no GitHub
.venvs/demo/bin/python cookbook/05_agent_os/32_github/basic.py --check

# Serve for the App
unset AGENT_OS_PORT    # serve on 7777, where ngrok forwards
export GITHUB_WEBHOOK_SECRET=$(cat ~/.agno_github_webhook_secret)
export GITHUB_APP_ID=<App ID>
export GITHUB_APP_PRIVATE_KEY_PATH=<path to the .pem>
export GITHUB_REPOSITORY=<owner>/<repo>
.venvs/demo/bin/python cookbook/05_agent_os/32_github/basic.py
```

Open an issue on the repository. The server prints the event, then reads the
issue back with the installation's token:

```
issues.opened on <owner>/<repo> #2 by <you>: Export fails
Read #2 with installation 12345678's token: open, 0 comments
```

`GITHUB_APP_PRIVATE_KEY` can hold the PEM contents instead of a path.

## Check the deliveries

- The App's **Advanced** tab lists recent deliveries with the response, and can
  redeliver one.
- ngrok's inspector at http://127.0.0.1:4040 shows each request and response,
  and can replay one.
- A free ngrok URL changes on every restart; update the App's **Webhook URL**
  when it does.

## Without an App

A repository webhook with a personal token also works for receiving events: set
the same secret on the webhook, leave `GITHUB_APP_ID` unset, and set
`GITHUB_BOT_LOGIN` to the account that will post Agno's comments so its events
are ignored.

```bash
gh api repos/$GITHUB_REPOSITORY/hooks -X POST -f name=web \
  -f 'config[url]=<ngrok URL>/github/events' -f 'config[content_type]=json' \
  -f "config[secret]=$GITHUB_WEBHOOK_SECRET" \
  -f 'events[]=issues' -f 'events[]=issue_comment'
```
