# Human Approvals

These cookbooks demonstrate the **requires_approval** and **log_approval** features for human-in-the-loop (HITL) approval workflows.

## Approval Types

### `requires_approval=True` (Blocking)

Creates a persistent approval record **before** the tool executes. The agent pauses and an approval record with `approval_type="required"` and `status="pending"` is written to the database. External systems can then list, inspect, and resolve those approvals.

### `log_approval=True` (Audit Logging)

Creates an approval record **after** the HITL interaction resolves. The record has `approval_type="logged"` and is immediately in a final state (`status="approved"` or `status="rejected"`). Useful for audit trails without blocking on external approval systems.

`log_approval=True` requires at least one HITL flag (`requires_confirmation`, `requires_user_input`, or `external_execution`). If both `requires_approval` and `log_approval` are set, `requires_approval` takes precedence.

## Examples

### `requires_approval` (Blocking Approvals)

| File | Description |
|------|-------------|
| `approval_basic.py` | Basic agent approval with SQLite - shows tool pause, DB record creation, and resolution |
| `approval_async.py` | Async variant of the basic approval flow |
| `approval_team.py` | Team-level approval - member agent tool triggers team pause with approval record |
| `approval_list_and_resolve.py` | Simulates the full API workflow: pause, list pending, resolve via DB, continue |
| `approval_user_input.py` | Approval with user input - `requires_approval` + `requires_user_input` |
| `approval_external_execution.py` | Approval with external execution - `requires_approval` + `external_execution` |

### `log_approval` (Audit-Logged Approvals)

| File | Description |
|------|-------------|
| `log_approval_confirmation.py` | Logged approval with confirmation - shows both approval and rejection paths |
| `log_approval_user_input.py` | Logged approval with user input |
| `log_approval_external.py` | Logged approval with external execution |
| `log_approval_async.py` | Async variant of logged approval with confirmation |
| `log_approval_overview.py` | Mixed overview - both `requires_approval` and `log_approval` in one agent |

## Key Concepts

- `@tool(requires_approval=True)` - Creates a blocking approval record (`approval_type="required"`) before tool execution.
- `@tool(requires_confirmation=True, log_approval=True)` - Logs the HITL resolution result (`approval_type="logged"`) after tool execution.
- Approval records are stored in the `agno_approvals` table (configurable via `approvals_table`).
- Each approval has a status: `pending`, `approved`, `rejected`, `expired`, `cancelled`.
- The `approval_type` field distinguishes `"required"` (blocking) from `"logged"` (audit) records.
- The `update_approval` method uses an `expected_status` guard for atomic resolution (prevents race conditions).
- You can filter approvals by type: `db.get_approvals(approval_type="required")` or `db.get_approvals(approval_type="logged")`.

## Running

```bash
.venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_basic.py
```
