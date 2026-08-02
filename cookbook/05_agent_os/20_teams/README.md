# Microsoft Teams

The `MicrosoftTeams` interface connects an Agent, Team, or Workflow to the
Microsoft Bot Framework. It verifies the inbound Bot Framework JWT, maps Teams
users to AgentOS users and sessions, downloads inbound attachments, and returns
text through the same channel. These examples focus on behavior that is
specific to Teams rather than repeating generic Agent, Team, or Workflow
patterns.

## Files

| File | Demonstrates |
|---|---|
| `basic.py` | One persistent Agent on the default `/msteams` interface |
| `proactive_alert.py` | Push a message to a Teams user from a background task via `teams.send_alert(user_id, text)` |

## Install

Teams JWT validation depends on `pyjwt[crypto]`. Install the optional extra:

```bash
uv pip install "agno[microsoft-teams]"
```

## Prerequisites

All examples require an Azure Bot registration, a Microsoft Entra ID
application (single- or multi-tenant), and a public HTTPS endpoint that the
Bot Connector can reach.

| Variable | Purpose |
|---|---|
| `MICROSOFT_APP_ID` | Bot Framework application id |
| `MICROSOFT_APP_PASSWORD` | Client secret for the Bot Framework application |
| `MICROSOFT_APP_TENANT_ID` | Entra tenant guid; leave unset for multi-tenant bots |
| `MICROSOFT_APP_TYPE` | `MultiTenant`, `SingleTenant`, or `UserAssignedMSI` |
| `OPENAI_API_KEY` | Model calls for both `basic.py` and `proactive_alert.py` |

## Configure Microsoft

1. In the Azure Portal create an **Azure Bot** resource.
2. On the bot's **Configuration** page, generate a client secret for the
   Microsoft Entra ID application and copy the App ID.
3. Choose **Multi Tenant** unless the bot is scoped to a single tenant; the
   tenant guid is only required for single-tenant bots.
4. Set the **Messaging endpoint** to
   `https://your-public-domain/msteams/messages`.
5. Under **Channels**, add the **Microsoft Teams** channel.
6. Start the example and expose port 7777 through an HTTPS tunnel or a
   deployment. The endpoint must be reachable when Teams delivers the first
   message.
7. In the Teams admin center or Developer Portal, upload an app manifest that
   references the bot's App ID and install it into a team or personal chat.

For example:

```bash
export MICROSOFT_APP_ID="..."
export MICROSOFT_APP_PASSWORD="..."
export MICROSOFT_APP_TYPE="MultiTenant"
export OPENAI_API_KEY="..."

.venvs/demo/bin/python cookbook/05_agent_os/20_teams/basic.py
```

The server must be running and publicly reachable when the first Teams message
is sent, because the Bot Connector times out around fifteen seconds.

## Endpoints

Every single-interface example uses the default prefix:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/msteams/status` | Reports interface availability |
| `POST` | `/msteams/messages` | Accepts signed Bot Framework activities |

The default prefix is `/msteams` (not `/teams`) because AgentOS already exposes
`/teams/*` for its multi-agent Team resource.

AgentOS also exposes `/health`, `/config`, and its normal REST surface.

## Sessions and Commands

Each Teams user is mapped to a session id of the form
`teams:<entity_id>:<user_id>`, where `user_id` is the Entra `aadObjectId` when
available and the channel-scoped id otherwise. Send `/new` to start a fresh
conversation; the previous session is preserved in storage.

## Proactive Alerts

Every inbound message silently persists the caller's `serviceUrl`,
`conversation.id`, and the bot's `recipient` object into that user's latest
session (`session_data.teams_conversation_ref`). Any code with a reference to
the `MicrosoftTeams` instance can later push a message without an inbound
trigger:

```python
await teams.send_alert(user_id="29:1abc...", text="Analysis complete.")
```

Returns `True` on delivery, `False` if that user has never chatted with the
bot (no reference to send to). Safe to call from scheduled jobs, background
tasks, or other request handlers. See `proactive_alert.py` for a working
example.

### Finding a Recipient's `user_id`

`proactive_alert.py` reads the target `user_id` from the `ALERT_USER_ID`
environment variable. The value is whatever the interface used as the run's
`user_id`, which is the Microsoft Entra `aadObjectId` when Teams supplies
it and the channel-scoped `from.id` otherwise:

1. Start `basic.py` (or any bot backed by the same database).
2. Ask the target user to send one message to the bot from Teams.
3. In the server logs, look for a line of the form:

   ```text
   INFO Processing Teams message from <id-prefix>: hello
   ```

   The identifier before the colon is a prefix of the run's `user_id`.

4. Read the full identifier out of the session database:

   ```bash
   sqlite3 tmp/teams_alerts.db \
     "SELECT user_id FROM agno_sessions
      WHERE session_id LIKE 'teams:%'
      ORDER BY updated_at DESC LIMIT 1;"
   ```

5. Export that value and start `proactive_alert.py`:

   ```bash
   export ALERT_USER_ID="<full-user-id-from-the-query-above>"
   .venvs/demo/bin/python cookbook/05_agent_os/20_teams/proactive_alert.py
   ```

Proactive delivery only succeeds against a live conversation reference. Web
Chat conversations expire when the browser tab closes, and `send_alert` will
receive a `403` from the Bot Connector against a stale reference. Use a
reference captured from a real Teams client for reliable delivery.

## Webhook Security

Incoming POST requests are validated as Bot Framework JWTs. The interface
fetches Microsoft's JWKS from
`https://login.botframework.com/v1/.well-known/openidconfiguration`, caches
keys for twenty-four hours, and verifies signature, audience, issuer, and
expiration. Teams routes authenticate themselves and are therefore outside
AgentOS's central authorization middleware.

For local development against the Bot Framework Emulator, the library
supports:

```bash
export MICROSOFT_APP_SKIP_JWT_VALIDATION=true
```

Never use that bypass in production.

## Test Scope

`TEST_LOG.md` records construction plus a live round-trip through Azure
"Test in Web Chat" over an ngrok tunnel, and a follow-up install into an actual
Microsoft Teams client belonging to a user in a different tenant via that
tenant admin's "Manage apps" approval flow. Unit tests under
`libs/agno/tests/unit/os/interfaces/test_teams_*.py` cover JWT validation,
helper behavior, and `send_alert` semantics.
