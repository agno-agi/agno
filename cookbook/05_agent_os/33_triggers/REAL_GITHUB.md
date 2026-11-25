# Checking triggers against GitHub itself

`github_issues.py --check` signs its own deliveries. This page is the part it
cannot do: six checks against a real repository, with deliveries GitHub sends.
It takes about half an hour.

No secret is written in this page or in `TEST_LOG.md`. Environment variables are
given by name only.

## What you need

- A repository you administer, in an organization. Use a test repository.
- Three GitHub accounts, or two colleagues:
  - **a collaborator** on the repository with write access (you can be this one),
  - **an outside account** with no role on the repository,
  - **an organization member whose membership is private** and who has write
    access to the repository through a team or the organization's base
    permission, not as a direct collaborator. This one is for check 4.
- `ngrok` (`brew install ngrok`) and an `OPENAI_API_KEY`.
- A checkout of this branch with `./scripts/demo_setup.sh` run.

## 1. Create the GitHub App

GitHub → the organization's **Settings** → **Developer settings** → **GitHub
Apps** → **New GitHub App**.

| Field | Value |
| --- | --- |
| GitHub App name | Any unique name |
| Homepage URL | Any URL |
| Webhook → Active | Checked |
| Webhook URL | `<ngrok URL>/github/events` (step 2 gives the URL) |
| Webhook secret | A value you generate, e.g. `openssl rand -hex 32` |
| Repository permissions → **Issues** | Read-only |
| Repository permissions → **Metadata** | Read-only (GitHub selects it for every App) |
| Subscribe to events | **Issues**, **Issue comment** |
| Where can this GitHub App be installed? | Only on this account |

Leave every other permission at **No access**. This is all phase 1 uses:

- **Issues, read**: GitHub requires it to send the `issues` and `issue_comment`
  events. Labels arrive as the `labeled` action of `issues`.
- **Metadata, read**: the permission lookup calls
  `GET /repos/{owner}/{repo}/collaborators/{username}/permission`.
- The App does not write to GitHub in phase 1, so it needs no write permission.

Then:

1. Note the **App ID** on the App's **General** page.
2. Under **Private keys**, **Generate a private key**. Keep the `.pem` file
   outside the repository.
3. **Install App** → the organization → **Only select repositories** → the test
   repository.
4. Remove any repository webhook that sends the same events, or each event
   arrives twice: `gh api repos/<owner>/<repo>/hooks`.

In the test repository, create a label named `agent`.

## 2. Run AgentOS and expose it

Terminal 1:

```bash
ngrok http 7777
```

Put the forwarding URL it prints, followed by `/github/events`, in the App's
**Webhook URL**.

Terminal 2, from the repository root. Set these variables; the values stay in
your shell:

| Variable | What it holds |
| --- | --- |
| `GITHUB_WEBHOOK_SECRET` | The App's webhook secret |
| `GITHUB_REPOSITORY` | `owner/name` of the test repository |
| `GITHUB_APP_ID` | The App ID |
| `GITHUB_APP_PRIVATE_KEY_PATH` | Path to the `.pem` file |
| `OPENAI_API_KEY` | For the triage agent |

```bash
unset AGENT_OS_PORT
rm -f tmp/triggers.db
.venvs/demo/bin/python cookbook/05_agent_os/33_triggers/github_issues.py
```

The cookbook declares three triggers: `triage-issues` (a new issue, continued by
comments), `triage-labeled` (the label `agent` added to an issue) and a daily
schedule. With `GITHUB_APP_ID` set it passes the App's credentials to the
source, which turns the permission lookup on.

To read the result of a check, in a third terminal with the same variables:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/33_triggers/github_issues.py --events
```

Each line is one stored event:
`delivery id | kind | key | trigger | status | session | reason or error`.

GitHub's own record is on the App's **Advanced** tab, under **Recent
deliveries**: the request it sent and the response it got.

## 3. The checks

Run them in order. For each, do the action, wait for the run to end (the server
prints a line when it does), then read the events.

| # | Action on GitHub | Expected in the events | Expected on GitHub's delivery |
| --- | --- | --- | --- |
| 1 | The collaborator opens an issue with a description. | One `issues.opened` event for `triage-issues`, status `success`, with a session id. | Response 202, `"status": "accepted"` |
| 2 | Anyone with a role on the repository comments on that issue. | One `issue_comment.created` event for `triage-issues`, status `success`, **the same session id** as check 1. | 202, `accepted` |
| 3 | The outside account opens an issue. | One `issues.opened` event, status `ignored`, with the reason "`<account>` has read access" (or "none access") "to `<owner>/<name>`; write access starts a run", which also mentions `allow="anyone"` and `issues.labeled`. No run. | 202, `accepted`: GitHub is asked about the account after the delivery is answered |
| 4 | The private member opens an issue. | One `issues.opened` event, status `success`. Record the `author_association` GitHub sent (see below). | 202, `accepted` |
| 5 | On the App's **Advanced** tab, open the delivery of check 1 and click **Redeliver**. | **No new event**: still one row for that delivery id, and no second run. | 202, `"duplicate": true` |
| 6 | A maintainer adds the label `agent` to the outside account's issue from check 3. | One `issues.labeled` event for `triage-labeled`, status `success`. The `issues.opened` event from check 3 is still `ignored`. | 202, `accepted` |

### Check 4, in detail

GitHub's documentation does not say what `author_association` it sends for a
member whose organization membership is private. Three reports say
`CONTRIBUTOR` or `NONE`. This check settles it for your organization.

Find what GitHub sent: on the App's **Advanced** tab, open the delivery and look
for `"author_association"` under `"issue"` in the payload.

- **`MEMBER`**: the payload was enough. The event ran without the lookup, and
  the check passes. Write down that the lookup was not exercised.
- **`CONTRIBUTOR` or `NONE`**: the payload understated the sender, so the event
  was accepted and GitHub was asked when it was claimed. It passes if the event
  ended as `success`. If it ended as `ignored` with "has read access" or "has
  none access", the member does not have write access to the repository: fix
  the access and open another issue.
- **`failed`** with "GitHub refused the credentials": the App is not installed
  on the repository, or it lacks the Metadata permission.

Check 3 is the same lookup refusing someone. To see the payload check alone,
stop the server, `unset GITHUB_APP_ID`, start it again and have the outside
account open another issue: the delivery is answered `"status": "ignored"` at
once, and the reason names the account's `author_association`.

### If a check fails

- **No delivery on the Advanced tab**: the App is not installed on the
  repository, or it is not subscribed to the event.
- **Delivery failed with 403**: `GITHUB_WEBHOOK_SECRET` is not the App's secret.
- **Delivery failed with a timeout or 502**: ngrok is not forwarding to port
  7777, or the server is not running.
- **`ignored` with "repository ... is not watched"**: `GITHUB_REPOSITORY` is
  not the repository that sent the event.
- **Every event arrives twice**: a repository webhook is still configured
  beside the App.

## 4. What to record

Add an entry to `TEST_LOG.md` under a heading `### github_issues.py against
GitHub`, with:

- The date, the commit of this branch, and the database used.
- For each of the six checks: PASS or FAIL, the event's status, and for check 2
  that the session ids matched.
- For check 4: the `author_association` GitHub sent, and whether the lookup was
  exercised.
- For check 5: the response to the redelivery.
- Anything GitHub did that this page does not describe.

Do not record the webhook secret, the App's private key, any token, or the
names of private accounts.

## 5. Clean up

Stop the server and ngrok. Uninstall the App from the repository, or delete the
App, and delete the private key file.
