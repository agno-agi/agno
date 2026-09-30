# iMessage

Connect an Agent, Team, or Workflow to direct iMessage text conversations using
the `IMessage` interface and [BlueBubbles](https://bluebubbles.app/).
`basic.py` serves a persistent assistant with an explicit sender allowlist.

## Prerequisites

- A Mac signed into Messages and running BlueBubbles Server. Keep the Mac awake.
- Complete the [BlueBubbles setup](https://docs.bluebubbles.app/server/installation-guides)
  and grant its required Messages access and automation permissions.
- Enable BlueBubbles' REST API and configure its server password. This example
  uses AppleScript for sending; BlueBubbles Private API is not required.
- The Agno demo environment with `agno[os]` and `openai` installed.

## Configure

```bash
export OPENAI_API_KEY="your-openai-key"
export BLUEBUBBLES_SERVER_URL="http://127.0.0.1:1234"
export BLUEBUBBLES_PASSWORD="your-bluebubbles-server-password"
export IMESSAGE_WEBHOOK_SECRET="a-long-random-url-safe-secret"
export IMESSAGE_ALLOWED_SENDERS="+15551234567,friend@example.com"
```

Use the port shown in BlueBubbles. The webhook secret is a separate secret that
you choose. Allowlist entries must exactly match the sender's phone number or
email address reported by BlueBubbles. The example requires an allowlist; an
empty value accepts no senders. In the interface API, `allowed_senders=None`
accepts all senders and `allowed_senders=[]` accepts none.

## Run and connect

```bash
.venvs/demo/bin/python cookbook/05_agent_os/28_imessage/basic.py
```

In BlueBubbles Server's **API & Webhooks** page, add a webhook subscribed to
**New Message** (`new-message`) using this URL, replacing the placeholder with
the value of `IMESSAGE_WEBHOOK_SECRET`:

```text
http://127.0.0.1:7777/imessage/webhook?token=YOUR_WEBHOOK_SECRET
```

The loopback addresses above assume both processes run on the same Mac. If
AgentOS runs elsewhere, BlueBubbles must be able to reach the webhook, and
AgentOS must be able to reach the BlueBubbles API. Use HTTPS for non-loopback
connections. Restrict external ingress to the webhook route; AgentOS's other
API routes need their own authentication if exposed.

BlueBubbles supports a webhook URL without a request signature. The URL token
authenticates incoming requests independently of AgentOS JWT authentication.
Treat that URL as a credential: redact query strings in proxy/tunnel logs and
keep BlueBubbles debug logging off. The example disables Uvicorn access logs.

Send an iMessage from an allowed contact to the Mac's Messages account. The
assistant replies in the same chat. Send a follow-up to use the saved history.
Messages marked `isFromMe` (including self-messages) are ignored to prevent loops.

| Route | Purpose |
|---|---|
| `GET /imessage/status` | Reports route availability; does not probe BlueBubbles. |
| `POST /imessage/webhook?token=...` | Accepts authenticated BlueBubbles events. |

## Scope and delivery

- Direct iMessage text only. Group chats, SMS/RCS, reactions, system events, and
  attachment-only messages are ignored. Attachments accompanying text are not
  passed to the model. Replies contain final text, without streaming or media.
- Pass exactly one of `agent=`, `team=`, or `workflow=`. Give it a stable ID and
  a database to retain history. Sessions include the interface prefix, entity,
  chat, and sender; `user_id` is `imessage:<sender-address>`.
- The bridge runs entities asynchronously by default. `get_router(use_async=False)`
  supports synchronous execution off the event loop when manually mounting it.
- Use one server worker. Runs are serialized per interface. Up to 100 messages
  can be pending, and the last 1,024 attempted message GUIDs are deduplicated in
  memory. Multiple workers or restarts do not share that state.
- A `processing` response means work was accepted into an in-process background
  task, not that the reply was delivered. There is no durable queue or automatic
  retry. Failures are logged by exception type; failed attempts are also
  deduplicated to avoid repeating tool side effects or an ambiguously delivered
  reply. Send a new message to try again.
- SQLite is for this local demo. Use PostgreSQL for deployed conversation storage;
  delivery tracking still needs a durable queue before reliable multiworker use.

The transport follows BlueBubbles' [REST API and webhook documentation](https://docs.bluebubbles.app/server/developer-guides/rest-api-and-webhooks)
and its [webhook dispatcher](https://github.com/BlueBubblesApp/bluebubbles-server/blob/master/packages/server/src/server/services/webhookService/index.ts).
