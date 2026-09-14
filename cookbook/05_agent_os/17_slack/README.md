# Slack

The `Slack` interface connects an Agent, Team, or Workflow to Slack through
signed event and interaction webhooks handled by Slack's Bolt framework. It
supports streamed replies, plan-mode tool cards, Slack's agent messaging
experience (session status, a native stop button, onboarding, suggested
prompts), a Home tab, files, workspace search, per-thread sessions, and
human-in-the-loop forms.

**Requirement:** `slack_sdk >= 3.44.0` and `slack_bolt >= 1.28.0`
(`pip install "agno[slack]"`). The demo environment installs both.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | One persistent Agent; DMs versus channel mention filtering |
| `streaming_ux.py` | Suggested prompts, loading messages, and plan-mode task cards |
| `agent_messaging.py` | Suggested prompts, onboarding, session status, and the stop button |
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

### 2. Enable Agents & AI Apps and the Home Tab

This is required for streaming, session status, and workspace search.

1. In the sidebar, click **Agents & AI Apps**.
2. Toggle **Agent or Assistant** to **On**. New apps get the **Agent** view;
   an older app on the **Assistant** view keeps working because the interface
   falls back to the assistant APIs automatically. Switching an existing app
   to the Agent view cannot be undone.
3. Under **Suggested Prompts**, select **Dynamic**.
4. Click **Save**.
5. In **App Home**, turn on the **Home Tab** and keep the **Messages Tab** on.

Enabling Agents adds the `assistant:write` scope. You can also import
`libs/agno/agno/os/interfaces/slack/manifest.json` as an app manifest and
replace the two `YOUR-URL` placeholders.

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
| `app_home_opened` | Set suggested prompts, send the onboarding message, and publish the Home tab |
| `agent_session_stopped` | Show Slack's native stop button and cancel the run when it is pressed |
| `agent_session_title_changed` | Mirror a renamed thread onto the Agno session name |
| `app_context_changed` | Pass what the user is looking at to the agent as context |
| `assistant_thread_started` | Assistant view only: set prompts and receive the workspace-search action token |
| `assistant_thread_context_changed` | Assistant view only: refresh thread context |

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

- `loading_text` and `loading_messages` update the session status
  (`loading_messages` only rotate on the Assistant view).
- `suggested_prompts` populate the Messages tab and new threads.
- `task_display_mode="plan"` shows tool work as plan cards.

Enable **Agents & AI Apps** and keep `slack_sdk` current for this surface.

## Agent Messaging Experience

`agent_messaging.py` turns on everything Slack's agent messaging offers:

| Option | What the user sees |
|---|---|
| `suggested_prompts` | A list of strings shown above the composer when the app is opened (use `{"title", "message"}` dicts when a shorter label is wanted). Up to four. |
| `onboarding_message` | One direct message the first time a user opens the Messages tab. Remembered in the database when one is configured. |
| `stop_message` | Posted in the thread when the user presses Slack's stop button. The run is cancelled through Agno's cancellation manager. Only the person who sent the message (or approved the paused step) can stop it; anyone else gets an ephemeral note and the reply continues in a fresh streamed message, because Slack closes the original one as soon as stop is pressed. |
| `session_api` | `"auto"` (default) uses `agents.sessions.*` and falls back to `assistant.threads.*` the first time Slack rejects it; `"agents"` or `"assistant"` pin one. |

Suggested prompts are the only Slack surface that sends a message on the
user's behalf when clicked, and on the Agent view they live at the top of the
Messages tab, not per thread. Follow-up questions after a reply therefore have
no native home there; the interface does not render the Agent's `followups`
in Slack.

Session status follows the run: processing while it works, suspended while a
human-in-the-loop card waits, active when done. Renaming a thread in Slack
renames the Agno session; the interface also names new threads after the first
message. What the user is looking at (`app_context_changed`) is passed to the
run as the `Slack context` dependency.

The stop button and the cancellation registry are per process. With several
uvicorn workers the stop event can reach a worker that is not running the
thread; that worker only clears the session status. Run a Slack-facing AgentOS
with one worker if the stop button matters.

## Home Tab

When the Home Tab is enabled in App Home, opening it shows the entity's name
and description and a "Powered by AgentOS" link to os.agno.com. There is
nothing to configure.

`per_user_thread_sessions=True` keys sessions per participant instead of per
thread, so two people in one channel thread keep separate histories. Cards
written in that mode carry the exact session id. Leave it off when a thread's
participants should share one conversation.

## Long-Running Sync Tools

Slack retries an event when it does not receive a 200 within three seconds.
The interface acknowledges before the run starts, but a sync tool that blocks
the event loop for longer than that (a package install, a long shell command)
can delay the acknowledgement of *other* incoming events. Retries are handled
by remembering each `event_id` for ten minutes, so a retried event runs at
most once per process. To avoid the delay itself, write long tools as `async
def`, or avoid attaching async tool hooks to sync tools, which forces the
sync tool onto the event loop.

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
credentials and verify app lifespan, `/health`, `/config`, and the exact
events/interactions route pairs. Bolt looks up the bot identity lazily, so no
Slack API call happens at construction. They do not
claim a real Slack installation, event delivery, interaction resume, tool
request, model inference, or outbound message.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bot does not respond | Event URL is unverified, the app is not invited, or required events are missing |
| DMs work but channel messages do not | `app_mention`/`message.channels` is missing or the app is not in the channel |
| Streaming returns `internal_error` | Agents & AI Apps is off, `assistant:write` is missing, or the app was not reinstalled |
| No task cards | `slack_sdk` is older than 3.44.0 |
| No suggested prompts | `app_home_opened` (Agent view) or `assistant_thread_started` (Assistant view) is not subscribed, **Suggested Prompts** is not set to **Dynamic** under Agents & AI Apps, or the app was not reinstalled. Failed calls are logged as warnings with Slack's error code. |
| No stop button while the agent works | `agent_session_stopped` is not subscribed, or the app is still on the Assistant view |
| Home tab is empty | The Home Tab is off in App Home, or `app_home_opened` is not subscribed |
| Workspace search reports no action token | The run did not start from a Slack Assistant thread |
| HITL buttons do nothing | Interactivity is disabled or its request URL is wrong |
| Webhook returns 401 | The app's signing secret does not match the interface, or the request is older than five minutes |
