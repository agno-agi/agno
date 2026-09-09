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
| `proactive_alert.py` | Push a message to a Teams user from a background task via `teams.asend_alert(user_id, text)` (or its sync `send_alert` wrapper) |

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
| `MICROSOFT_APP_ID` | Bot Framework application id; optional only in the credential-free bypass mode below |
| `MICROSOFT_APP_PASSWORD` | Client secret for the Bot Framework application; optional under the same mode |
| `MICROSOFT_APP_TENANT_ID` | Entra tenant guid. Required for a single-tenant bot, which is what the portal creates; leave unset only if your app registration is multi-tenant |
| `OPENAI_API_KEY` | Model calls for both `basic.py` and `proactive_alert.py` |

Managed Identity (`UserAssignedMSI`) is not supported: the interface authenticates
with a client secret.

## Configure Microsoft

1. In the Azure Portal create an **Azure Bot** resource. The portal creates a
   single-tenant app registration, so keep the **App tenant ID** it shows you --
   the token endpoint needs it, and the multi-tenant option the older docs
   describe is no longer offered here.
2. Copy the **Microsoft App ID** from the bot's **Configuration** page.
3. Create a client secret: **Configuration → Manage Password**, which opens the
   app registration's **Certificates & secrets**, then **New client secret**.

   > Copy the **Value** column, not **Secret ID**. Both are shown once, side by
   > side, and only the Value works. A Secret ID is a 36-character guid; a Value
   > is around 40 characters and usually contains a `~`. The Value is masked
   > permanently as soon as you navigate away, so copy it before doing anything
   > else. Sending the wrong one fails as
   > `AADSTS7000215: Invalid client secret provided`, and only on the *outbound*
   > leg -- inbound messages still arrive and are processed, which makes it look
   > like a delivery problem rather than a credential one.

4. Set the **Messaging endpoint** to
   `https://your-public-domain/msteams/messages`.
5. Under **Channels**, add the **Microsoft Teams** channel.
6. Start the example and expose port 7777 through an HTTPS tunnel or a
   deployment. The endpoint must be reachable when Teams delivers the first
   message.

```bash
export MICROSOFT_APP_ID="..."
export MICROSOFT_APP_PASSWORD="..."       # the secret Value, not the Secret ID
export MICROSOFT_APP_TENANT_ID="..."      # required for a single-tenant bot
export OPENAI_API_KEY="..."

.venvs/demo/bin/python cookbook/05_agent_os/26_teams/basic.py
```

Verify the credentials before sending a message. This is the same client-credentials
exchange the interface makes for every outbound reply:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST "https://login.microsoftonline.com/$MICROSOFT_APP_TENANT_ID/oauth2/v2.0/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$MICROSOFT_APP_ID" \
  -d "client_secret=$MICROSOFT_APP_PASSWORD" \
  -d "scope=https://api.botframework.com/.default"
```

`200` means replies will send. `401` means the secret or the tenant is wrong; drop
the `-o /dev/null` to read Microsoft's error, which names the field.

The server must be running and publicly reachable when the first Teams message
is sent, because the Bot Connector times out around fifteen seconds.

## Installing the Bot in Teams

**For a personal chat**, no app package is needed. Once the Teams channel is
connected, open the bot directly:

```text
https://teams.microsoft.com/l/chat/0/0?users=28:<your-app-id>
```

That is the same link the channel's **Open in Teams** action produces, and it is
enough to exercise everything except channels and group chats.

**For channels and group chats**, upload an app package: a `manifest.json`
declaring `scopes` of `personal`, `team` and `groupChat`, plus a 192x192 colour
icon and a 32x32 transparent outline icon, zipped with all three at the root.
Upload it under **Apps → Manage your apps → Upload an app**.

The manifest's `id` and the bot's `botId` are independent values. Set `botId` to
the app id; give `id` a fresh guid. Reusing the app id for both is refused with
"the app's external ID is already being used" whenever a catalogue entry already
holds it.

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

Each Teams user starts on a session id of the form
`teams:<entity_id>:<user_id>`, where `user_id` is the Entra `aadObjectId` when
available and the channel-scoped id otherwise. Send `/new` to start a fresh
conversation — it gains a random suffix and becomes the one subsequent messages
resolve to; the previous session is preserved in storage.

## Proactive Alerts

Every inbound message persists the caller's `serviceUrl`, `conversation.id`,
and the bot's `recipient` object onto the session that run used
(`session_data.teams_conversation_ref`). Any code with a reference to the
`MicrosoftTeams` instance can later push a message without an inbound
trigger:

```python
# Inside a coroutine (scheduled job, background task, another handler)
await teams.asend_alert(user_id="29:1abc...", text="Analysis complete.")

# From a synchronous script / simple scheduler
teams.send_alert(user_id="29:1abc...", text="Analysis complete.")
```

Delivery uses the newest session that carries a reference, which is not always
the newest session — `/new` starts one without a reference until the user's next
message, and alerts keep working across that gap.

Both return `True` on delivery and `False` when the entity has no database, when
the session lookup fails, or when none of that user's recent sessions carries a
reference (typically because they have never chatted with the bot). Failing to
deliver to a reference that does exist is the one case that raises instead of
returning `False`, so a caller that loops on the return value has to handle both.
Call it from scheduled jobs, background tasks, or other request handlers; see
`proactive_alert.py` for a working example of both paths.

### Finding a Recipient's `user_id`

`proactive_alert.py` reads the target `user_id` from the `ALERT_USER_ID`
environment variable. The value is whatever the interface used as the run's
`user_id`, which is the Microsoft Entra `aadObjectId` when Teams supplies
it and the channel-scoped `from.id` otherwise:

1. Start `basic.py` (or any bot backed by the same database).
2. Ask the target user to send one message to the bot from Teams.
3. In the server logs, look for a line of the form:

   ```text
   INFO Processing Teams message from user <id-prefix>
   ```

   The trailing identifier is a prefix of the run's `user_id`. The message text
   is logged separately at debug level.

4. Read the full identifier out of that example's session database. Each example
   writes its own: `basic.py` uses `tmp/teams_basic.db`, `proactive_alert.py`
   uses `tmp/teams_alerts.db`. Query the one the bot you messaged was running.

   ```bash
   sqlite3 tmp/teams_basic.db \
     "SELECT user_id FROM agno_sessions
      WHERE session_id LIKE 'teams:%'
      ORDER BY updated_at DESC LIMIT 1;"
   ```

5. Export that value and start `proactive_alert.py`:

   ```bash
   export ALERT_USER_ID="<full-user-id-from-the-query-above>"
   .venvs/demo/bin/python cookbook/05_agent_os/26_teams/proactive_alert.py
   ```

   The two examples register different agent ids against different databases, so
   a reference stored while `basic.py` was running is not visible here. Message
   the bot once with `proactive_alert.py` running before expecting a delivery.

Proactive delivery only succeeds against a live conversation reference, and its
two failure modes want opposite handling. `False` means no reference is stored
yet — retryable, and the thing to wait for. A reference that exists but no longer
works is rejected by the Bot Connector, which surfaces as a raised
`httpx.HTTPError` rather than `False`; retrying that address is a loop that never
ends. The same clause also catches a transport failure, which is not a dead
address but is not worth a retry every fifteen seconds either.
`proactive_alert.py` catches the raise, logs which user it was for, and stops.
References captured from a real Teams client outlast ones from a Web Chat test
window, so prefer them for anything you want to keep working.

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

The bypass applies **only when neither credential is configured**. With an app id
set there is a real audience to verify against, so the flag is ignored and inbound
activities are validated as usual — the variable cannot downgrade a configured
deployment, and setting one credential without the other is refused at startup.
Outbound delivery is unavailable in this mode (fetching a bot token needs the
client secret), so it exercises the inbound path only.

## Test Scope

Unit tests under `libs/agno/tests/unit/os/interfaces/test_teams_*.py` cover JWT
validation, helper behavior, and `asend_alert` / `send_alert` semantics. They run
offline. `TEST_LOG.md` records what each example was run against.
