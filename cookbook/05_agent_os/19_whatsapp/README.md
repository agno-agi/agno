# WhatsApp

The `Whatsapp` interface connects an Agent, Team, or Workflow to the WhatsApp
Cloud API. It verifies Meta webhooks, maps phone numbers to AgentOS users and
sessions, downloads inbound media, and returns text or media through the same
channel. These examples focus on behavior that is specific to WhatsApp rather
than repeating generic Agent, Team, or Workflow patterns.

## Files

| File | Demonstrates |
|---|---|
| `basic.py` | One persistent Agent on the default `/whatsapp` interface |
| `interactive.py` | Reply buttons, lists, location pins, and reactions |
| `media.py` | Inbound multimodal messages and outbound generated image/video artifacts |
| `reasoning_agent.py` | Separate reasoning messages with `show_reasoning=True` |
| `multiple_instances.py` | Two credential sets mounted under separate webhook prefixes |

## Prerequisites

All examples require a Meta app with the WhatsApp product enabled, a WhatsApp
Business phone-number ID, and a public HTTPS endpoint that Meta can reach.

| Variable | Purpose |
|---|---|
| `WHATSAPP_ACCESS_TOKEN` | Authorizes WhatsApp Cloud API calls |
| `WHATSAPP_PHONE_NUMBER_ID` | Selects the sending phone number |
| `WHATSAPP_VERIFY_TOKEN` | Shared value used during Meta's GET verification challenge |
| `WHATSAPP_APP_SECRET` | Verifies `X-Hub-Signature-256` on incoming POST requests |
| `OPENAI_API_KEY` | Runs `basic.py`, `interactive.py`, `reasoning_agent.py`, and `multiple_instances.py` |
| `GOOGLE_API_KEY` | Runs the Gemini Agent and image tool in `media.py` |
| `FAL_API_KEY` | Runs video generation in `media.py` |

`media.py` also requires the `fal-client` package, which is included by the
Agno `fal` optional dependency.

## Configure Meta

1. Create or select a Meta app with the WhatsApp product enabled.
2. In the WhatsApp setup page, copy the access token and phone-number ID.
3. In **App settings > Basic**, copy the app secret.
4. Choose a private verification token; the same string must be entered in
   Meta and exported as `WHATSAPP_VERIFY_TOKEN`.
5. Start one example and expose port 7777 through an HTTPS tunnel or deployment.
6. Configure the callback URL as
   `https://your-public-domain/whatsapp/webhook`.
7. Subscribe the app to the `messages` webhook field.
8. Add the phone you will message from as a test recipient when using Meta's
   development phone number.

For example:

```bash
export WHATSAPP_ACCESS_TOKEN="..."
export WHATSAPP_PHONE_NUMBER_ID="..."
export WHATSAPP_VERIFY_TOKEN="choose-a-private-value"
export WHATSAPP_APP_SECRET="..."
export OPENAI_API_KEY="..."

.venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/basic.py
```

The server must be running and publicly reachable when Meta performs the
verification challenge.

## Endpoints

Every single-interface example uses the default prefix:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/whatsapp/status` | Reports interface availability |
| `GET` | `/whatsapp/webhook` | Handles Meta's verification challenge |
| `POST` | `/whatsapp/webhook` | Accepts signed message events |

AgentOS also exposes `/health`, `/config`, and its normal REST surface.

`multiple_instances.py` mounts the same three operations under both `/basic`
and `/web-research`.

## Run an Example

```bash
.venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/basic.py
.venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/interactive.py
.venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/media.py
.venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/reasoning_agent.py
.venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/multiple_instances.py
```

Only one standalone example should bind to port 7777 at a time.

## Interactive Messages

`interactive.py` enables only the four channel-native tools used by its flow:
reply buttons, list messages, location pins, and reactions. It explicitly uses
Graph API version `v25.0`, matching the interface implementation.

The interface adds two values to the Agent's run context:

- `User's WhatsApp number`
- `Incoming WhatsApp message ID`

The Agent must pass the number as `recipient` to every WhatsApp tool and the
message ID to `send_reaction`. Reply-button events are presented to the Agent
as the displayed button title. List replies are presented as
`title: description`; the internal row IDs are not included.

WhatsApp allows one to three reply buttons and at most ten rows across a list's
sections. When a WhatsApp tool sends a message directly, the interface avoids
sending the Agent's final text again.

## Media

Incoming images, video, audio, and documents are downloaded from Meta and
passed to the Agent as Agno media objects. Media returned by the Agent or its
tools is uploaded to Meta before it is sent to the user.

`media.py` uses Gemini for inbound understanding, Gemini's image tool for still
images, and Fal for short generated video. Set `media_timeout` on `Whatsapp`
when large Meta downloads or uploads need more than the 30-second default.
This timeout is separate from `WhatsAppTools(timeout=...)`.

Outbound images must be JPEG or PNG. Other image formats are skipped by the
interface. Provider and WhatsApp size or format limits still apply to audio,
video, and documents.

## Webhook Security

Incoming POST requests are checked against `WHATSAPP_APP_SECRET` using the
`X-Hub-Signature-256` header. WhatsApp routes authenticate themselves and are
therefore outside AgentOS's central authorization middleware.

For local construction or payload development only, the library supports:

```bash
export WHATSAPP_SKIP_SIGNATURE_VALIDATION=true
```

Never use that bypass in production.

The optional `enable_encryption=True` setting protects phone-derived user IDs
and session IDs stored in the database:

```bash
export WHATSAPP_ENCRYPTION_KEY="$(openssl rand -hex 32)"
```

The key must contain exactly 64 hexadecimal characters. This setting is not
webhook encryption. If `send_user_number_to_context=True`, the raw phone number
is still supplied to the model so interactive tools can address the user.

## Multiple Instances

`multiple_instances.py` requires separate values:

```bash
export BASIC_WHATSAPP_ACCESS_TOKEN="..."
export BASIC_WHATSAPP_PHONE_NUMBER_ID="..."
export BASIC_WHATSAPP_VERIFY_TOKEN="..."

export RESEARCH_WHATSAPP_ACCESS_TOKEN="..."
export RESEARCH_WHATSAPP_PHONE_NUMBER_ID="..."
export RESEARCH_WHATSAPP_VERIFY_TOKEN="..."
```

Each Meta webhook points to its matching prefix:

- `https://your-public-domain/basic/webhook`
- `https://your-public-domain/web-research/webhook`

There is one important current limitation: signature verification reads one
process-wide `WHATSAPP_APP_SECRET`; `Whatsapp` does not yet accept an app secret
per interface. Separate Meta apps normally have distinct secrets, so the file
demonstrates construction, configuration isolation, and prefix routing but does
not prove a secure two-app production deployment. Run separate AgentOS
processes for separate app secrets until the interface supports per-instance
signature secrets. Do not use the signature-validation bypass as a production
workaround.

## Test Scope

The entries in `TEST_LOG.md` are construction smokes. They use sentinel
credentials to construct each app and exercise only local `/health`, `/config`,
status, and GET verification-challenge routes. They do not claim successful
Meta delivery, provider inference, signed webhook processing, or generated
media delivery.
