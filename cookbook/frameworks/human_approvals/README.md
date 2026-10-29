# Native harness approvals

Claude and Codex permission requests automatically reach AgentOS when the agent
has a database, including one supplied by `AgentOS(db=...)`. Configure the native
harness policy; no separate Agno approval mode is needed.
The native process remains alive while the persisted run is PAUSED. Resolving an
approval and choosing **Continue Run** delivers the decision to that same process.
It never replays the prompt or starts a replacement turn.

## Run

Run from the repository root with Docker running and the development `.venv`
installed with `agno[os,postgres,claude,codex]`. The code uses the standard local
Postgres URL (`postgresql+psycopg://ai:ai@localhost:5532/ai`) and the image
`agno-sandbox:human-approvals` directly. No database, image, queue, or Redis
environment variables are needed.

Start the cookbook Postgres container if it is not already running, then build
the sandbox image from this checkout:

```sh
./cookbook/scripts/run_pgvector.sh
.venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:human-approvals
```

The image includes both native SDKs, including the tested `openai-codex==0.163.0`
transport. Supply the model credentials for whichever agent you want to test:
`ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) for Claude, `OPENAI_API_KEY` for
Codex. If your credentials are already exported, no additional setup is needed.
Start the server:

```sh
.venv/bin/python cookbook/frameworks/human_approvals/agentos.py
```

Connect `http://localhost:7777` in AgentOS. Select either agent and ask:

> Create approval-test.txt containing "approved" in the workspace. Request native
> permission if needed. If permission is rejected, stop without a workaround.

Inspect the command or file change in
**Approvals**, approve or reject, then choose **Continue Run**. Approval alone does
not execute it. Under user isolation, existing administrator approval rules apply.
The requesting user cannot approve by forging a tool result on the continue API.

Native policy determines which operations ask; this does not make every tool call
require confirmation. Claude uses `permission_mode="default"`, `"acceptEdits"`, or
`"plan"`; `"bypassPermissions"` and `"dontAsk"` keep their native behavior. Explicit
Claude permission callbacks remain in charge when supplied.

Codex uses its native `approval_policy="on-request"` or `"untrusted"`; `"never"`
does not ask. Its `sandbox_mode` independently controls filesystem isolation.
Omitting `approval_policy` lets the native configuration/profile select the policy.
The SDK's existing `approval_mode="auto_review"` and `"deny_all"` remain supported
and are not routed to the UI. Codex config values `approval_policy` and
`approvals_reviewer` are also respected. Do not combine `approval_policy` with the
SDK's `approval_mode` shorthand.

This example runs one AgentOS process with `QueueConfig(durable=True, db=db)`.
Postgres stores the queue and approvals; event streaming and cancellation use the
process-local defaults. Redis is not required. Checkpoints are stored under
`tmp/native-approval-checkpoints`. To change the database or image, edit the values
in `agentos.py`.

## Lifecycle and limits

- Only approve-once and reject are supported. Edited arguments, new prompts,
  forks, regeneration, and broader policy grants are refused by native continuation.
- `approval_timeout` bounds each request. Sandbox and queue active execution
  budgets exclude human waiting, with an additional cumulative waiting budget
  equal to `approval_timeout`. Heartbeats and session exclusivity remain held.
- Refreshing or closing a browser does not cancel a background run. This cookbook
  serves one local API process; it does not configure multi-replica coordination.
- AgentOS starts agents that can request approval in the background automatically;
  nonstreaming HTTP submissions return 202 and the run can be polled or streamed.
- A lost native process cannot be resumed from an approval;
  the run fails and the previous completed checkpoint remains the recovery point.
- Cancellation and expiry never approve a pending action. Approval history is
  retained; terminal runs no longer offer executable requirements.
- Direct in-process runs need a persistent event loop while waiting. Use
  `arun(background=True)` or AgentOS. `acontinue_run` and `continue_run` deliver
  decisions; they do not create that original execution.
- Approval delivery currently supports standalone agents. Team members and workflow
  steps keep running operations their native policy permits; an actual request for
  human permission fails explicitly before that action executes.

This example uses PostgreSQL. Direct development runs can use SQLite. A database
is required to persist and deliver decisions. Failures can be retried before any
approval request; once a request is made, Agno never retries the native turn.
