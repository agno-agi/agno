# Test Log: 17_slack

Tested on 2026-11-12 against a real Slack workspace, with a development Slack app
reached through a cloudflared tunnel, `slack_bolt` 1.30 and `slack_sdk` 3.43.

- Messages were posted by real Slack users through their user tokens and
  delivered by Slack to the running example. Replies were read back with the
  bot token, and each Slack API call's outcome was taken from the server's
  `slack_sdk` debug log.
- Each example was served unchanged and sent at least one real message in the
  agent view. The same interface code was also run in the assistant view, by
  switching the app's manifest and restoring it afterwards.
- No button press and no Stop was simulated against Slack. Rows marked "Live"
  were done by hand in the Slack client: clicks, Stop presses, renames and
  typed channel mentions. Slack shows Stop only in the agent view.
- Rows marked "test server" ran the same interface code from a small server
  that sets up the case no example covers. Rows marked "signed delivery" were
  posted to the server as events signed with the app's real signing secret;
  their replies still went through the real Slack Web API.
- Channel mentions in these runs came from a test app whose user-token posts
  carry a `bot_id`, so they were answered without streaming. A channel mention
  typed in the Slack client was answered in a thread under it, in both views.
- The web search backend returned no results during the runs, so the examples
  with web search were asked not to search.

### basic.py

**Status:** PASS

**Description:** A DM and a channel mention to the persistent Agent.

**Result:**
- The DM reply streamed, and the channel mention was answered once in its
  thread.
- Test server: `streaming=False` answered in a DM and a channel, in both views.
  A follow-up in a channel thread kept the thread's session, and a thread reply
  without a mention was ignored.
- Live, agent view: the Messages tab showed the default prompt, a question
  streamed with Slack's "is working" status and the thread got a title, Stop
  mid-answer ended the reply and the run was saved as cancelled, and a renamed
  thread kept its title after another message.
- Live, assistant view: a new thread showed the suggested prompt, a question
  streamed with its status, and a channel mention was answered in its thread.

---

### streaming_ux.py

**Status:** PASS

**Description:** A real DM to the streaming example, a shutdown mid-reply, and
the streaming paths it teaches on a test server.

**Result:**
- The reply streamed with its status line.
- Stopping the server mid-reply ended the message with "_Stopped._", and the
  server exited in 32 seconds.
- Test server: the status was set on every run and cleared on the non-streamed
  paths, in both views.
- Test server: an answer over 12,000 characters continued in a new message
  headed "_(continued)_", in both views (11,413 + 9,255 characters in the agent
  view).
- Test server: an answer that ran past Slack's 10-minute stream limit moved to
  a new message at about 9 minutes, in both views.
- Test server: two messages in one thread set the title once, in both views.
- Live: suggested prompts, a user's thread rename, and the Stop button were
  checked with `basic.py`, which runs the same interface code. In the agent
  view, `loading_messages` rotated and Slack drew its own "is working" in place
  of the status text; in the assistant view, Slack answered the Messages-tab
  prompt call with `not_agent_app` and the interface logged one warning.

---

### slack_tools.py

**Status:** PASS

**Description:** One real message to the `SlackTools` analyst in the agent view.

**Result:** The message was answered in its thread.

---

### user_memory.py

**Status:** PASS

**Description:** A fact told in one thread, then asked about in a new thread.

**Result:** The new thread's answer recalled the fact ("Helix"), so the memory
followed the user across threads.

---

### team.py

**Status:** PASS

**Description:** One real message to the support Team.

**Result:**
- The Team answered.
- Live: member steps showed as task cards. With the `search:read.*` scopes
  added, a channel mention and a DM searched Slack and returned linked results;
  without them Slack sent no `action_token`.
- Test server: when a member failed, the leader still answered and no error
  reply was posted, in both views.

---

### workflow.py

**Status:** PASS

**Description:** One real message to the research-then-writing Workflow.

**Result:**
- The Workflow answered.
- Live: the steps showed as task cards and the full brief arrived; Stop mid-run
  ended the steps as "stopped".
- Test server: a Workflow answered in a DM and a channel, and a paused Workflow
  posted its pause notice in both places, in both views.

---

### multiple_bots.py

**Status:** PASS

**Description:** One real message to each prefix, `/research` and `/analyst`.

**Result:** Both bots answered. Only one Slack app was available, so both
prefixes used that app's token; two separate Slack apps were not run.

---

### peer_agents.py

**Status:** PASS

**Description:** One real message to each prefix, `/coordinator` and
`/researcher`.

**Result:** Both answered. The bot-to-bot handoff needs two Slack apps and was
not run.

---

### hitl_confirmation.py

**Status:** PASS

**Description:** A request that calls the confirmation-required cancellation
tool.

**Result:**
- The run paused and Slack showed the Approve / Deny card.
- Live: Approve ran the tool and the run finished, in both views. Deny left the
  tool unrun and passed the typed reason to the run. Slack offers no Stop while
  the card waits. Signed delivery: an `agent_session_stopped` event for the
  waiting run cancelled it and froze the card to "Stopped".

---

### hitl_user_input.py

**Status:** PASS

**Description:** A request that files a ticket needing operator input.

**Result:** The run paused and Slack showed the input form. The submit click was
not part of the live session.

---

### hitl_external_execution.py

**Status:** PASS

**Description:** A request that calls the external-execution deploy tool.

**Result:** The run paused and Slack showed the external-execution card. The
click was not part of the live session.

---

### hitl_incident_commander.py

**Status:** PASS

**Description:** An incident report that starts the compound flow.

**Result:** The run paused on its first requirement and Slack showed the
feedback form. The click was not part of the live session.

---

### access_control.py

**Status:** PASS

**Description:** A message from the mapped operator; the same message from an
unmapped Slack user.

**Result:**
- The mapped user's message ran as the principal and paused on the approval
  card, in both views.
- The unmapped user got the private "not linked" notice and nothing ran, in
  both views.
- Test server: a mapped user whose principal lacks the run permission got
  "Not run: Permission required: ..." and nothing ran, while a mapped user with
  the role ran.
- The approver click was not part of the live session.

---

### claude_harness.py

**Status:** PASS

**Description:** A plain question; "Run python shipping.py and tell me what it
prints."; a decision made through AgentOS's continue route.

**Result:**
- The plain question was answered, in both views.
- `python shipping.py` paused and Slack showed the Approve / Deny card, in both
  views. `ls -la` ran without a card, because Claude Code pre-approves
  read-only commands.
- Live: Approve on the `python shipping.py` card ran it and Claude Code
  reported its output, in both views.
- FAIL for a decision made through AgentOS's continue route: the run completed
  for the API client, but nothing was posted into the Slack thread and the card
  stayed live. A later message in the thread saw the result. README Limits
  describes this.

---

### codex_harness.py

**Status:** PASS

**Description:** A plain question and a command that needs approval.

**Result:**
- With the Codex API-key login, the plain question was answered and the
  command paused on the Approve / Deny card, in both views.
- Live: Approve ran the command and Codex reported the result, in both views.
- With a ChatGPT login that was out of usage, Slack showed the Codex error.
- A decision made through AgentOS's continue route did not reach the Slack
  thread, as for `claude_harness.py`.

---

### sandbox_review.py

**Status:** PASS

**Description:** The sandboxed Codex reviewer in `agno-sandbox:local` with
`approval_policy="untrusted"` on the durable queue; a decision made through
AgentOS's continue route.

**Result:**
- A command paused and Slack showed the Approve / Deny card, in both views.
- Live: two cards approved in a row ran their commands in the container, and
  the review finished. A card whose arguments exceed Slack's 200-character card
  body lists the argument names, and the full values follow once below it.
- FAIL for a decision made through AgentOS's continue route: the run completed,
  but nothing was posted into the Slack thread, as for `claude_harness.py`.

---

### super_agent.py

**Status:** PASS

**Description:** A Task started from Slack; a restart after delivery; the server
killed mid-Task; a reply under another user's root message; two Tasks at once
(signed delivery).

**Result:**
- The Task's receipt ended the turn, and its result was posted once into the
  thread that started it, in both views.
- Live: the Task was queued, and its result was posted once into the same DM
  thread about 35 seconds later.
- After a restart, no second result was posted.
- With the server killed mid-Task, one outcome was posted after the restart
  (the run ended in an error, because the queue runs a Task at most once).
- A Task started from a reply under another user's root message posted its
  result there.
- Signed delivery: two Tasks started at once each posted into their own thread,
  and a SIGTERM or a SIGKILL mid-Task each delivered the outcome exactly once.

---

## Validation

- `Slack(...)` raises `ValueError` when the token, the signing secret, or the
  entity is missing.
- With `OS_SECURITY_KEY` set, Slack still answered. AgentOS routes answered 401
  without the key and 200 with it; unsigned `/slack/events` and
  `/slack/interactions` requests answered 401, also with the key as bearer.
- A message sent while the server was down was redelivered by Slack and
  answered once.
- `slack_bolt` 1.29.0, the floor of the `slack` extra, answered real messages.
- The shipped `manifest.json` passed Slack's `apps.manifest.validate` with no
  warnings.
- `chat.stopStream` with `session_status="processing"` and `"suspended"`
  returned ok in both views; an invalid value returned `invalid_arguments`.

---
