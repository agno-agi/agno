# Human in the Loop

AgentOS has two related pause contracts:

- `@tool(requires_confirmation=True)`, `requires_user_input=True`, and
  `external_execution=True` create an ephemeral requirement on a persisted
  run. Resolve the returned tool or requirement and call that run's
  `/continue` route.
- `@approval(type="required")` creates a persistent database record as well as
  a pause. An administrator resolves it through `POST
  /approvals/{approval_id}/resolve` or the control-plane Approvals page before
  the run continues.

`@approval(type="audit")` is different again: it records the result of an
ephemeral HITL decision after resolution. It must decorate a tool that already
has one of the three HITL flags.

## Setup

From the repository root:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=your-key
```

Every server listens on port 7777. Start one at a time. Each file includes its
matching HTTP continuation client behind `--demo`.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Confirm an ephemeral agent tool and resend the updated `tools` payload. |
| `user_input.py` | Resolve two successive member-tool input pauses through a team's `requirements` payload. |
| `external_execution.py` | Execute a side effect in the client, attach its result, and continue the team. |
| `with_approval_record.py` | List, resolve, and continue one persistent required approval. |
| `audit_record.py` | Confirm an ephemeral pause and read back the resulting audit approval. |
| `team_approval.py` | Compare persistent approval tools owned by a team leader and a member agent. |
| `workflow_hitl.py` | Resolve pre-step confirmation, step user input, and post-step output review over HTTP. |

## Run an example

Terminal 1:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/basic.py
```

Terminal 2:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/basic.py --demo
```

Use the same two-terminal pattern for the other files. `workflow_hitl.py` is
credentials-free because every workflow step uses a local executor function.

Agent pauses serialize pending decisions in `tools`. Team pauses serialize
`RunRequirement` objects in `requirements`. Workflow pauses serialize
`StepRequirement` objects in `step_requirements`. Send the same shape back to
the component-specific nested `/continue` route after resolving it.

For persistent team approvals, the approval record remains the administrative
decision of record. The continuation payload also carries that approved
decision into the paused team or member requirement.

See [`cookbook/04_workflows/08_human_in_the_loop`](../../04_workflows/08_human_in_the_loop)
for the complete workflow HITL primitive matrix.
