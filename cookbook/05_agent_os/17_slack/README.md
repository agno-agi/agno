# Slack

The `Slack` interface connects an Agent, Team, or Workflow to Slack through
signed event and interaction webhooks. It supports streamed replies, plan-mode
tool cards, suggested prompts, files, workspace search, per-thread sessions,
and human-in-the-loop forms.

**Requirement:** `slack_sdk >= 3.40.0` for streaming with plan-mode task cards.
The demo environment installs the supported Slack dependencies.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | One persistent Agent; DMs versus channel mention filtering |
| `streaming_ux.py` | Suggested prompts, loading messages, and plan-mode task cards |
| `slack_tools.py` | Channel history, threads, workspace search, and file transfer |
| `user_memory.py` | Cross-thread user memory with resolved Slack identity |
| `team.py` | A specialist support Team with workspace search |
| `workflow.py` | A sequential research-then-writing Workflow |
| `multiple_bots.py` | Two separately credentialed Slack apps on one AgentOS |
| `peer_agents.py` | Safe, asymmetric responses to another Slack app |
| `hitl_confirmation.py` | Confirmation before a destructive tool call |
| `hitl_user_input.py` | Structured user input collected in Slack |
| `hitl_external_execution.py` | Show tool arguments and collect an external result |
| `hitl_incident_commander.py` | Compound incident flow using all pause types |

## Slack App Setup

Follow these steps to create and configure a Slack app for use with Agno.

### 1. Create the App

1. Go to https://api.slack.com/apps and click **Create New App**.
2. Choose **From scratch**, give it a name, and select your workspace.
3. On the **Basic Information** page, copy the **Signing Secret**.

### 2. Enable Agents & AI Apps

This is required for streaming and workspace search.

1. In the sidebar, click **Agents & AI Apps**.
2. Toggle **Agent or Assistant** to **On**.
3. Under **Suggested Prompts**, select **Dynamic**.
4. Click **Save**.

Enabling this adds the `assistant:write` scope.

### 3. Add OAuth Scopes

In **OAuth & Permissions > Bot Token Scopes**, add the scopes used by the
example you plan to run:

| Scope | Purpose |
|---|---|
| `app_mentions:read` | Receive mentions in channels |
| `assistant:write` | Stream replies, set status, and provide dynamic prompts |
| `chat:write` | Send replies |
| `im:history` | Receive and read direct-message history |
| `channels:read`, `groups:read` | Resolve public and private channel metadata |
| `channels:history`, `groups:history` | Read public and private channel history |
| `files:read`, `files:write` | Download incoming files and upload results |
| `users:read` | Resolve Slack users |
| `users:read.email` | Resolve a stable email identity for `user_memory.py` |
| `search:read.public` | Search public workspace messages |
| `search:read.files` | Include files in workspace search |
| `search:read.users` | Resolve people in workspace search |

The common streaming set is `app_mentions:read`, `assistant:write`,
`chat:write`, and `im:history`. Every Python file's `Slack scopes:` line lists
its exact set.

Install the app to the workspace, then copy its **Bot User OAuth Token**
(`xoxb-...`). Reinstall the app after changing scopes.

### 4. Subscribe to Events

1. In **Event Subscriptions**, enable events.
2. Set **Request URL** to:

   ```text
   https://YOUR-PUBLIC-HOST/slack/events
   ```

3. Subscribe to the bot events the app needs:

| Event | Purpose |
|---|---|
| `app_mention` | Receive channel mentions |
| `message.im` | Receive direct messages |
| `message.channels` | Receive public-channel messages, including peer-app messages |
| `message.groups` | Receive private-channel messages |
| `assistant_thread_started` | Set prompts and receive the workspace-search action token |
| `assistant_thread_context_changed` | Refresh Assistant thread context |

4. Save changes and reinstall the app.

Slack sends a signed URL-verification request when the endpoint is configured,
so AgentOS must already be publicly reachable.

### 5. Enable Interactivity

The four `hitl_*.py` examples require Slack interactivity:

1. In **Interactivity & Shortcuts**, enable interactivity.
2. Set **Request URL** to:

   ```text
   https://YOUR-PUBLIC-HOST/slack/interactions
   ```

3. Save changes.

Without this endpoint, approval buttons and submitted input cannot resume a
paused run.

### 6. Set Environment Variables

```bash
export SLACK_TOKEN="xoxb-..."
export SLACK_SIGNING_SECRET="..."
export OPENAI_API_KEY="sk-..."
```

`SLACK_TOKEN` is the Bot User OAuth Token. `SLACK_SIGNING_SECRET` is the
Signing Secret from **Basic Information**.

### 7. Start a Tunnel

Slack needs a public HTTPS URL. For local development:

```bash
ngrok http 7777
# or
cloudflared tunnel --url http://localhost:7777
```

Copy the public URL into both Slack request URLs. If the tunnel hostname
changes, update both settings.

### 8. Run an Example

```bash
.venvs/demo/bin/python cookbook/05_agent_os/17_slack/basic.py
```

DM the app or mention it in a channel.

## Routes

A default Slack interface mounts:

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/slack/events` | URL verification and incoming Slack events |
| `POST` | `/slack/interactions` | HITL buttons and form submissions |

AgentOS also exposes `GET /health` and `GET /config`. A Slack interface has no
separate status route. Custom prefixes replace `/slack`; each app in a
multi-bot example must point its event and interaction URLs at its own prefix.

## Messages, Threads, and User Identity

With `reply_to_mentions_only=True`, the interface processes `app_mention`
events in channels and suppresses ordinary non-mention channel messages.
Direct messages are still answered. With the flag disabled, ordinary channel
messages are processed and duplicate `app_mention` events are ignored.

Each Slack thread becomes one AgentOS session. The current session key is:

```text
{entity_id}:{channel_id}:{thread_ts}
```

For a top-level message, its timestamp starts the thread. Replies reuse the
parent `thread_ts`. The channel ID prevents timestamp collisions across
channels. The resolver first checks the older `{entity_id}:{thread_ts}` form so
upgrades do not orphan existing history. Everyone replying in one channel
thread shares that conversation session.

By default, the run's `user_id` is the Slack member ID. With
`resolve_user_identity=True`, the interface calls `users.info`, uses the
member's email as the stable ID when Slack returns it, adds their display name
to run metadata, and falls back to the Slack ID on lookup failure.
`user_memory.py` uses this setting so memories can follow a person across
threads; it requires `users:read` and `users:read.email`.

## Streaming UX

Slack streaming is on by default. The interface opens `chat_stream`, appends
text as the run progresses, and renders tool activity as task cards.
`streaming_ux.py` makes the controls explicit:

- `loading_text` and `loading_messages` update Assistant status.
- `suggested_prompts` populate new Assistant threads.
- `task_display_mode="plan"` shows tool work as plan cards.

Enable **Agents & AI Apps**, subscribe to `assistant_thread_started`, and keep
`slack_sdk` current for this surface.

## Workspace Search Action

`SlackTools.search_workspace` uses Slack's
`assistant.search.context` action rather than the legacy message-search API.
Slack supplies a short-lived `action_token` on an Assistant thread event; the
interface places it in run metadata and the toolkit reads it at call time.
That means:

- Call it from a Slack Assistant thread, not from a console run.
- Grant `search:read.public`, `search:read.files`, and `search:read.users`.
- No `SLACK_USER_TOKEN` is needed for the examples in this lesson.
- Search visibility follows the Slack user's and workspace's permissions.

`slack_tools.py` combines this search with channel history, thread expansion,
and file transfer. `team.py` gives the same search action to one specialist.

## Multiple Bots and Peer Apps

Slack sends each app's events to one configured URL. `multiple_bots.py` mounts
two apps with separate tokens, signing secrets, and prefixes on one server.
Configure both the events and interactions URL for each app. Entity IDs and
channel/thread keys keep their sessions separate even in the same workspace.

```bash
export RESEARCH_SLACK_TOKEN="xoxb-..."
export RESEARCH_SLACK_SIGNING_SECRET="..."
export ANALYST_SLACK_TOKEN="xoxb-..."
export ANALYST_SLACK_SIGNING_SECRET="..."
```

| App | Events URL | Interactions URL |
|---|---|---|
| Research | `/research/events` | `/research/interactions` |
| Analyst | `/analyst/events` | `/analyst/interactions` |

Bot-authored messages are dropped by default. `respond_to_other_apps=True`
opts one interface into receiving messages from peer apps; messages from that
interface's own bot identity are still dropped. `peer_agents.py` deliberately
uses an asymmetric topology:

- The coordinator keeps `respond_to_other_apps=False` and hears humans.
- The researcher sets it to `True` and can hear the coordinator.

This allows one-way delegation without an automatic ping-pong loop. Do not
enable peer responses symmetrically unless your application adds another
explicit loop guard.

The peer example also needs the Researcher's Slack app user ID so the
coordinator can emit a real `<@USER_ID>` mention:

```bash
export COORDINATOR_SLACK_TOKEN="xoxb-..."
export COORDINATOR_SLACK_SIGNING_SECRET="..."
export RESEARCHER_SLACK_TOKEN="xoxb-..."
export RESEARCHER_SLACK_SIGNING_SECRET="..."
export RESEARCHER_SLACK_USER_ID="U..."
```

Configure the coordinator at `/coordinator/events` and
`/coordinator/interactions`, and the researcher at `/researcher/events` and
`/researcher/interactions`.

## Human-in-the-Loop

Slack renders paused tool requirements as interactive cards and resumes the
persisted run through `/slack/interactions`. This lesson keeps one focused
example for confirmation, user input, and external execution, plus one
compound incident-response flow.

For an `external_execution=True` tool, the Python entrypoint does not run
before the pause. Slack displays the tool name and arguments, the operator
performs that operation elsewhere, and the value they submit becomes the tool
result used by the resumed run. Both external-execution examples put the exact
operator command in a visible tool argument.

Team-level approval and member-pause propagation are generic AgentOS behavior,
so they live in
[`05_human_in_the_loop/team_approval.py`](../05_human_in_the_loop/team_approval.py).
The Slack interface will render those Team requirements through the same
interaction route.

## Test Scope

`TEST_LOG.md` records credential-gated construction smokes. They use sentinel
credentials, patch only Slack's startup `auth_test`, and verify app lifespan,
`/health`, `/config`, and the exact events/interactions route pairs. They do not
claim a real Slack installation, event delivery, interaction resume, tool
request, model inference, or outbound message.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bot does not respond | Event URL is unverified, the app is not invited, or required events are missing |
| DMs work but channel messages do not | `app_mention`/`message.channels` is missing or the app is not in the channel |
| Streaming returns `internal_error` | Agents & AI Apps is off, `assistant:write` is missing, or the app was not reinstalled |
| No task cards | `slack_sdk` is older than 3.40.0 |
| No suggested prompts | `assistant_thread_started` is not subscribed or Dynamic prompts are off |
| Workspace search reports no action token | The run did not start from a Slack Assistant thread |
| HITL buttons do nothing | Interactivity is disabled or its request URL is wrong |
| Webhook returns 403 | The app's signing secret does not match the interface |
