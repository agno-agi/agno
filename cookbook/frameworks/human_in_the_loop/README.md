# Harness permission requests in the chat

Claude Code and Codex ask before running a tool their native permission policy does not allow. With a
database, including one supplied by `AgentOS(db=...)`, each request pauses the Agno run with a tool that
requires confirmation, the same human-in-the-loop flow as an Agno agent's confirmation tool. The person in
the chat confirms or rejects it; there is no admin approval and nothing appears on the Approvals page.

Their multiple-choice questions to the user pause the same way, as user feedback like Agno's `ask_user`
tool: Claude's `AskUserQuestion` and Codex's `request_user_input`. The chat shows the questions and options;
the selections, or an answer typed instead, go back to the harness as its answers.

The native Claude or Codex process stays alive while the run is paused. Continuing the run with the tool
confirmed or rejected delivers that answer to the same process, which carries on from where it asked. It
never replays the prompt or starts a replacement turn.

## Run

Run from the repository root with Docker running and the development `.venv` installed with
`agno[os,postgres,claude,codex]`. Start Postgres and build the sandbox image from this checkout:

```sh
./cookbook/scripts/run_pgvector.sh
.venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:human-in-the-loop
```

Supply the model credentials for the agent you want to test: `ANTHROPIC_API_KEY` (or
`CLAUDE_CODE_OAUTH_TOKEN`) for Claude, `OPENAI_API_KEY` for Codex. Then start the server:

```sh
.venv/bin/python cookbook/frameworks/human_in_the_loop/agentos.py
```

Connect `http://localhost:7777` in AgentOS, select either agent and ask:

> Create confirm-test.txt containing "confirmed" in the workspace.

The run pauses with a confirmation card for the command or file change. Confirm or reject it in the chat;
the run continues in the same message. To try a question, ask:

> Ask me which color I prefer, Red or Blue, then tell me what I picked.

The run pauses with the question and its options. Pick one, or type your own answer, and the agent replies
with it.

## Which requests pause

Native policy decides which operations ask, so not every tool call needs confirmation.

- **Claude:** `permission_mode="default"`, `"acceptEdits"` or `"plan"` can ask; `"bypassPermissions"` and
  `"dontAsk"` keep their native behavior. A `can_use_tool` callback or `permission_prompt_tool_name` you
  supply stays in charge.
- **Questions:** Claude's `AskUserQuestion` pauses whenever Agno handles its permission requests. Codex
  offers `request_user_input` outside plan mode only with
  `config={"features": {"default_mode_request_user_input": True}}`, a flag Codex marks as under
  development. Codex's built-in instructions also tell it to ask required questions in plain text, so the
  example's `instructions` ask it to use the tool. When every question is skipped, Claude is told the user declined to answer; Codex receives
  empty answers. Codex questions marked secret are refused, because answers are stored on the run.
- **Codex:** `approval_policy="on-request"` or `"untrusted"` can ask; `"never"` does not. `sandbox_mode`
  separately controls filesystem isolation. Leaving `approval_policy` unset uses the native configuration's
  policy. The SDK's `approval_mode="auto_review"` and `"deny_all"` keep their behavior and never pause. Codex
  permission requests and questions need `openai-codex==0.163.0`.

## How it works

- **The paused run is the shared state.** Its requirements are what the chat confirms; its metadata records
  each pending request with a digest of the exact action. Continuing the run checks the answer against that
  action, records it and moves the run from PAUSED to RUNNING in one conditional write. The waiting process
  reads the answer from the run, so any API replica can serve the continuation, and a repeated or stale
  continuation finds the run no longer paused.
- **The chat stream ends at the pause,** as for an Agno agent. Continuing opens the stream for the rest of
  the run, until it completes or pauses again.
- **One request at a time.** When a harness asks for several permissions at once, the run pauses for each in
  turn.
- **Sandboxed agents** wait inside their container. The coordinator records each request on the run under
  its execution lease and delivers the answer to the container; another API replica can take over the
  execution if the first one is lost.

## Limits

- Permission requests support confirm and reject; questions support selecting options or typing an
  answer. Edited arguments, new input, forks, regeneration and standing permission grants are refused.
- `hitl_timeout` (default 900 seconds) bounds each request. Queued and sandboxed runs also keep a
  cumulative waiting budget of that length, separate from their active execution budget.
- AgentOS runs these agents in the background, so a wait outlives the browser connection; nonstreaming HTTP
  submissions return 202.
- Without a sandbox, the waiting process lives in the API worker that started the run. If that worker is
  lost, the run fails instead of replaying; a sandboxed run survives losing its API worker.
- Team members and workflow steps keep running what their native policy permits; an actual permission
  request inside one fails before the action runs.
- This example runs one AgentOS process with `QueueConfig(durable=True, db=db)`; Redis is not required.
  Checkpoints are stored under `tmp/native-hitl-checkpoints`.
