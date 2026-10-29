# Native harness approvals

`approval_mode="human"` forwards Claude and Codex permission requests to AgentOS.
The native process remains alive while the persisted run is PAUSED. Resolving an
approval and choosing **Continue Run** delivers the decision to that same process.
It never replays the prompt or starts a replacement turn.

## Run

Install `agno[os,postgres,claude,codex]` from this checkout. Human Codex approvals
currently require `openai-codex==0.163.0`; the transport refuses untested versions.
Set `DATABASE_URL`, `ANTHROPIC_API_KEY`, and `OPENAI_API_KEY`, then run:

```sh
python cookbook/frameworks/human_approvals/agentos.py
```

Connect `http://localhost:7777` in AgentOS. Select an agent and ask it to run a
command that needs native permission. Inspect the command and arguments in
**Approvals**, approve or reject, then choose **Continue Run**. Approval alone does
not execute it. Under user isolation, existing administrator approval rules apply.
The requesting user cannot approve by forging a tool result on the continue API.

Native policy still determines which operations ask. Claude's `permission_mode`
and Codex's `sandbox_mode` remain separate from who reviews requests. This does not
make every tool call require confirmation. Existing defaults are unchanged.

For Docker, also set `REDIS_URL` for shared queue coordination and `AGNO_SANDBOX_IMAGE` to a sandbox image built with this Agno version
and both native SDKs. This local example keeps checkpoints under `tmp/native-approval-checkpoints`; use a shared checkpoint store such as S3 for replicas on different hosts. The control plane checks the runtime's approval capability
before starting the harness. Upgrade existing Docker and AgentCore images together
with the API: old images are rejected rather than silently denying or approving.
The same authenticated decision RPC is used by Docker and AgentCore. Sandbox
runtime credentials and its local approval database stay inside the sandbox;
control-plane database credentials are not sent to it.

## Lifecycle and limits

- Only approve-once and reject are supported. Edited arguments, new prompts,
  forks, regeneration, and broader policy grants are refused by native continuation.
- `approval_timeout` bounds each request. Sandbox and queue active execution
  budgets exclude human waiting, with an additional cumulative waiting budget
  equal to `approval_timeout`. Heartbeats and session exclusivity remain held.
- Refreshing or closing a browser does not cancel a background run. Decisions are
  persisted and can be delivered from another API replica.
- A surviving sandbox worker can be reattached using its original execution
  journal and identity. A lost native process cannot be resumed from an approval;
  the run fails and the previous completed checkpoint remains the recovery point.
- Cancellation and expiry never approve a pending action. Approval history is
  retained; terminal runs no longer offer executable requirements.
- Direct in-process runs need a persistent event loop while waiting. Use
  `arun(background=True)` or AgentOS. `acontinue_run` and `continue_run` deliver
  decisions; they do not create that original execution.
- Human mode currently supports standalone agents. Team members and workflow
  steps reject it before execution; their existing non-human modes are unchanged.

This example uses PostgreSQL. Direct development runs can use SQLite. Human mode
requires a database on the agent and disables automatic native-turn retries.
