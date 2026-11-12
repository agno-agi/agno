# Slack

The `Slack` interface connects an Agent, Team, Workflow, or external agent
(Claude Code, Codex) to Slack through signed event and interaction webhooks. It
supports Slack's agent view and assistant view, streamed replies with a Stop
button, plan-mode tool cards, suggested prompts, files, workspace search,
per-thread sessions, human-in-the-loop cards, and Super Agent Task results.

## Install

```bash
pip install -U "agno[slack]"
```

The `slack` extra installs `slack_bolt>=1.29` and `slack_sdk>=3.43`. Slack Bolt
receives the requests: it checks the signature, answers URL verification, and
hands each event to the interface. The demo environment installs both.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | One persistent Agent; DMs versus channel mention filtering |
| `streaming_ux.py` | Loading messages, suggested prompts, task cards, long replies, and Stop |
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
| `access_control.py` | `users=` maps Slack users to principals; `approvers=` names who may approve or stop |
| `claude_harness.py` | A Claude Code agent with native tool approvals |
| `codex_harness.py` | A Codex agent with native command approvals |
| `sandbox_review.py` | A sandboxed Codex reviewer in a Docker container, with native approvals |
| `super_agent.py` | Super Agent starts Company Tasks and posts their results back to the thread |

## Slack App Setup

### 1. Create the App from the Manifest

The quickest setup uses the manifest shipped with the interface,
[`manifest.json`](../../../libs/agno/agno/os/interfaces/slack/manifest.json):

1. Go to https://api.slack.com/apps and click **Create New App**.
2. Choose **From an app manifest**, select your workspace, and paste the
   manifest.
3. Replace both `https://YOUR-URL` values with your public host (see step 5).
4. Create the app, then install it to the workspace.
5. On **Basic Information**, copy the **Signing Secret**. On **OAuth &
   Permissions**, copy the **Bot User OAuth Token** (`xoxb-...`).

### 2. Agent View

The manifest turns on Slack's agent view:

```json
"features": {
    "app_home": {"messages_tab_enabled": true, "messages_tab_read_only_enabled": false},
    "agent_view": {"agent_description": "Ask me anything."}
}
```

In the agent view, people talk to the app from its Messages tab and from
threads. The interface:

- sets suggested prompts on the Messages tab when it opens (`app_home_opened`),
  when the app's Slack settings allow it (see Limits);
- streams replies with task cards and status messages;
- names a direct-message thread from its first message, once, so a title the
  user changes is kept (Slack has thread titles only in direct messages);
- stops a run when the user presses Stop (`agent_session_stopped`).

Apps built on the older assistant view keep working. Keep the `assistant_view`
feature and the `assistant_thread_started` event in that app's settings, and new
threads get their suggested prompts from that event.

### 3. Events

The manifest subscribes to these bot events:

| Event | Purpose |
|---|---|
| `app_mention` | Receive channel mentions |
| `message.im` | Receive direct messages and agent view messages |
| `app_home_opened` | Set suggested prompts when the Messages tab opens |
| `agent_session_stopped` | Stop the run when the user presses Stop |

Add these only when you need them:

| Event | Purpose |
|---|---|
| `message.channels`, `message.groups`, `message.mpim` | Answer channel and group-DM messages without a mention (`reply_to_mentions_only=False`, or `peer_agents.py`) |
| `assistant_thread_started` | Suggested prompts on new threads of an assistant view app |

The events URL is `https://YOUR-PUBLIC-HOST/slack/events`. Slack sends a signed
URL-verification request when it is saved, so AgentOS must already be reachable.

### 4. Scopes

The manifest asks for these bot scopes:

| Scope | Purpose |
|---|---|
| `app_mentions:read` | Receive mentions in channels |
| `assistant:write` | Stream replies, set status and thread titles, and set suggested prompts |
| `chat:write` | Send replies, cards, and ephemeral notices |
| `im:history` | Receive direct messages (`message.im`); read DM threads |
| `mpim:history` | Read group-DM threads |
| `channels:history`, `groups:history` | Read public and private channel threads |
| `channels:read`, `groups:read` | Resolve public and private channel names |
| `files:read`, `files:write` | Download incoming files and upload results |
| `users:read` | Resolve Slack users and bots |
| `users:read.email` | Resolve an email identity (`resolve_user_identity=True`, `user_memory.py`) |

The history scopes are needed for two reasons. Slack delivers a message event
only when the app holds the history scope of that conversation type. And Super
Agent reads the thread (`conversations.replies`) before it posts a Task result,
to check that the result is not already there; without the scope for that
conversation type, the result is never posted.

`SlackTools.search_workspace` (`slack_tools.py`, `team.py`) also needs
`search:read.public`, `search:read.files`, and `search:read.users`; without them
Slack sends no `action_token` and search fails. Every Python file's
`Slack scopes:` line lists its exact set. Reinstall the app after changing
scopes.

### 5. Interactivity

The manifest turns interactivity on, with the request URL
`https://YOUR-PUBLIC-HOST/slack/interactions`. Approval buttons and submitted
input resume paused runs through it.

### 6. Environment Variables

```bash
export SLACK_TOKEN="xoxb-..."
export SLACK_SIGNING_SECRET="..."
export OPENAI_API_KEY="sk-..."
```

`Slack(...)` raises `ValueError` when the token or the signing secret is
missing, from the arguments or from these variables.

### 7. Tunnel

Slack needs a public HTTPS URL. For local development:

```bash
ngrok http 7777
# or
cloudflared tunnel --url http://localhost:7777
```

Copy the public URL into the events and interactions request URLs. If the
tunnel hostname changes, update both.

### 8. Run an Example

```bash
.venvs/demo/bin/python cookbook/05_agent_os/17_slack/basic.py
```

Open the app's Messages tab, DM it, or mention it in a channel. After the app
switches to the agent view, reload Slack if the Messages tab still shows the old
view.

## Routes

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/slack/events` | URL verification and incoming Slack events |
| `POST` | `/slack/interactions` | HITL buttons and form submissions |

A request with a missing, bad, or stale signature gets `403`. Custom prefixes
replace `/slack`; each app in a multi-bot example points its event and
interaction URLs at its own prefix.

## Messages, Threads, and User Identity

With `reply_to_mentions_only=True`, the interface answers `app_mention` events
in channels and ignores other channel messages. Direct messages are always
answered. With the flag off, ordinary channel messages are answered and the
duplicate `app_mention` is ignored.

Each Slack thread becomes one AgentOS session:

```text
{entity_id}:{channel_id}:{thread_ts}
```

The resolver first checks the older `{entity_id}:{thread_ts}` form, so existing
history is kept. Everyone replying in one channel thread shares that session.
Each Slack message gets its own run id, so a message Slack delivers twice runs
once.

By default the run's `user_id` is the Slack member ID. With
`resolve_user_identity=True`, the interface uses the member's email when Slack
returns it and adds the display name to run metadata.

Claude Code and Codex take one turn per session at a time: a message that
arrives while one is working gets a short "still working" reply. An Agent or
Team runs both turns.

## Streaming and Stop

Streaming is on by default. `streaming_ux.py` shows the controls:

- `loading_messages` rotate in the status line while the run works. The agent
  view shows its own "is working" in place of `loading_text`; Slack documents
  `loading_text` as the status line of assistant-view apps.
- `suggested_prompts` show on the Messages tab and on new threads.
- `task_display_mode="plan"` shows tool calls as plan cards.

A reply longer than one Slack message, or a run longer than nine minutes,
continues in a new message in the same thread; open task cards move with it.

**Stop.** Pressing Stop on a streaming reply cancels the run and ends the
message with "Stopped". Stop works for Agents, Teams, Workflows, and external
agents. Slack offers no Stop while an approval card waits; a Stop pressed just
before the run paused still stops it and freezes the card to "Stopped". Only the
person who started the run, a Slack user mapped to the same principal, or a user
in `approvers=` can stop it; anyone else gets a private notice.

## Approvers and User Mapping

`access_control.py` shows both arguments:

```python
Slack(
    agent=agent,
    users={"U0123ABC": "billing-operator-1"},  # Slack member ID -> AgentOS principal
    approvers=["U0456DEF"],  # Slack member IDs who may approve or stop any run
)
```

The example reads the token key and both member IDs from the environment:

```bash
export JWT_VERIFICATION_KEY="..."
export SLACK_OPERATOR_ID="U..."
export SLACK_APPROVER_ID="U..."
```

- **`approvers=`**: Slack member IDs (not emails) that may approve, deny, or stop
  any run. Without it, only the person who started the run can.
- **`users=`**: maps Slack member IDs to AgentOS principals. Each message runs as
  the mapped principal, with the roles AgentOS authorization gives it, and the
  run's `user_id` is that principal. An unmapped user is told their account is
  not linked, and a disabled principal is refused. Slack requests carry no
  AgentOS token, so grants come from managed roles
  (`Authorization.define_role` and `assign`) or a provider that decides by
  principal; JWT scopes alone grant a mapped user nothing.

## Workspace Search Action

`SlackTools.search_workspace` uses Slack's `assistant.search.context` action.
Slack supplies a short-lived `action_token` on agent view and assistant view
messages; the interface puts it in run metadata and the toolkit reads it at call
time. Call it from a Slack message, not a console run, and grant the three
`search:read.*` scopes. Search visibility follows the Slack user's permissions.

## Multiple Bots and Peer Apps

Slack sends each app's events to one URL. `multiple_bots.py` mounts two apps
with separate tokens, signing secrets, and prefixes on one server.

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

Bot-authored messages are dropped by default. `respond_to_other_apps=True` opts
one interface into messages from peer apps; its own messages are still dropped.
`peer_agents.py` uses an asymmetric topology: the coordinator keeps
`respond_to_other_apps=False`, and the researcher sets it to `True`. That allows
one-way delegation without a ping-pong loop.

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

Slack renders paused tool requirements as cards and resumes the stored run
through `/slack/interactions`. The `hitl_*.py` files cover confirmation, user
input, external execution, and a compound incident flow. A second click on a
card that is already being submitted gets "Already submitted"; a card whose run
is no longer paused gets "This approval is no longer active".

Team-level approval lives in
[`05_human_in_the_loop/team_approval.py`](../05_human_in_the_loop/team_approval.py);
Slack renders those requirements through the same route.

## Claude Code and Codex Agents

`ClaudeAgent` and `CodexAgent` run behind the same interface. With a database
and approvals on (Claude's default permission mode; Codex
`approval_policy="untrusted"` or `"on-request"`), the agent asks for approval as
its permission settings decide; Claude Code, for example, runs read-only
commands such as `ls` without asking. Slack shows the request as an Approve /
Deny card, and the click answers the agent process that is still waiting. These
runs start in the background, so a request can wait longer than a Slack event
lives.

`claude_harness.py` also needs `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`
for Claude Code:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

- A request expires after the agent's `hitl_timeout` (900 seconds by default).
  A click after that answers "This approval is no longer active."
- A restart while a request is waiting ends that run, and its card reads
  "Stopped".
- Every external agent sees the Slack channel context as a block after the
  message. A non-sandboxed agent gets it in its prompt only, and the stored run
  keeps the user's text; a sandboxed agent gets it in its input, which is stored
  with the run.

### Sandboxed Agents and Approvals

A sandboxed agent (`sandbox=DockerSandbox(...)`) with approvals on works from
Slack. The approval reaches the agent inside the container, and the rest of the
answer streams into the same thread. Two requirements:

- the agent is listed in `AgentOS(agents=[...])`;
- AgentOS has a durable queue: `queue=QueueConfig(durable=True, db=db)`.

`sandbox_review.py` runs this way. It needs the runtime image and Postgres from
[`frameworks/sandbox`](../../frameworks/sandbox/README.md). Give the container
read-only repository access only.

## Super Agent

`super_agent.py` serves AgentOS's built-in Super Agent (`agent_os.manager`). It
is built inside AgentOS, so the interface is added after construction:

```python
agent_os = AgentOS(..., company=CompanyConfig(model=model), manager=OSManager(model=model))
agent_os.interfaces.append(Slack(team=agent_os.manager))
app = agent_os.get_app()
```

- Starting a Task ends the turn with a receipt in the thread. The Task runs in
  its own session on the durable queue.
- When the Task has a result (in review, done, or cancelled, or its run ended in
  an error), the result is posted once into the thread that started it, with its
  recorded evidence count. The posted message carries the Task and attempt in
  its message metadata, so a restart does not post it again.
- A result is posted only to the thread whose run started the Task, and only
  when the run's user wrote the Slack message that started it (read back from
  Slack). Anyone who asks in a thread gets their own Task's result there.

With `AgentOS(authorization=...)`, pass `users=`; `get_app()` refuses to serve
Super Agent under authorization without it. Each message then runs with the
mapped principal's roles.

## Limits

- **One worker per Slack app.** Event dedupe, approval claims, and the index of
  running turns that Stop uses are kept in process. Run each Slack app on a
  single worker.
- **Slack bypasses `OS_SECURITY_KEY`.** Slack requests are verified by their
  signature, not the AgentOS key. Without AgentOS `authorization=`, every member
  of the workspace can use the agent through Slack.
- **Super Agent trusts the caller's `user_id` with authorization off.** A result
  is posted only into a thread holding a real Slack message by that user, but
  the user id itself is not checked. For shared workspaces, turn on
  `authorization=` with `users=`.
- **An approval decided outside Slack does not post into the thread.** When a
  Claude Code or Codex approval is decided through the AgentOS API or UI, the run
  finishes, but nothing is posted into the Slack thread; the next click on the
  card answers "This approval is no longer active". A later message in the
  thread sees the result.
- **A paused Workflow step is resolved in AgentOS.** Slack shows "Run paused —
  please resolve it in AgentOS. The result shows there, not in this thread."
  Continuing the run in AgentOS completes it, but nothing is posted into the
  Slack thread.
- **Messages-tab prompts need the agent view.** In the assistant view Slack
  refuses them (`not_agent_app`): the interface logs one warning, and prompts on
  new threads are not affected. A client may need a reload to show them.
- **A restart stops replies still running after 30 seconds.** On shutdown, each
  Slack interface waits up to 30 seconds for its running replies, one interface
  after another, then cancels the rest; each cancelled reply ends with
  "Stopped".
- **Background runs whose live events end early.** When the live events of a
  Claude Code or Codex run end before the run finishes, the interface reads the
  stored run every second for up to the agent's `hitl_timeout`; a run still
  unfinished then ends in Slack as an error, even if it finishes later.
- **Approvals inside a Team member or a Workflow step.** A Claude Code or Codex
  member, or a workflow step, that asks for permission fails before the action
  runs; see [`frameworks/human_in_the_loop`](../../frameworks/human_in_the_loop/README.md).

## Test Scope

`TEST_LOG.md` records the runs of each example against a real Slack workspace.
On 2026-11-12 the client actions were also checked by hand, in the agent view
and the assistant view: streaming with the status line, the thread title, a
renamed title kept, a channel mention, prompts on the Messages tab and on new
threads, Approve and Deny, the Claude Code and Codex approval cards, the
sandboxed Codex reviewer, a Team with Slack search, and a Super Agent result
posted once. Stop, which Slack shows only in the agent view, was checked on a
streaming reply and on a Workflow. While an approval card waits, Slack offers no
Stop and the card's Deny ends the run; that stop path was checked with a signed
`agent_session_stopped` event, which cancelled the run and froze the card to
"Stopped".

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bot does not respond | Event URL is unverified, the app is not in the channel, or an event is not subscribed |
| DMs work but channel messages do not | `app_mention` is missing, or the app is not in the channel |
| Streaming returns `internal_error` | Agent view is off, `assistant:write` is missing, or the app was not reinstalled |
| No suggested prompts | `app_home_opened` is not subscribed, the Messages tab is off, the app is in the assistant view (a `not_agent_app` warning in the log), or the Slack client needs a reload |
| Stop does nothing | `agent_session_stopped` is not subscribed |
| "Your Slack account is not linked" | `users=` is set and the sender is not in it |
| Workspace search reports no action token | The run did not start from a Slack message, or the app lacks the `search:read.*` scopes |
| HITL buttons do nothing | Interactivity is off or its request URL is wrong |
| Webhook returns 403 | The app's signing secret does not match the interface |
