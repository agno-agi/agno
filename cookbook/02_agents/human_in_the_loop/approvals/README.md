# Human Approvals

These cookbooks demonstrate the **@approval** decorator for human-in-the-loop (HITL) approval workflows.

## Approval Types

### `@approval` (Blocking, type="required")

Creates a persistent approval record **before** the tool executes. The agent pauses and an approval record with `approval_type="required"` and `status="pending"` is written to the database. External systems can then list, inspect, and resolve those approvals.

When used without arguments, `@approval` defaults to `type="required"` and auto-sets `requires_confirmation=True` if no other HITL flag is set.

### `@approval(type="audit")` (Audit Logging)

Creates an approval record **after** the HITL interaction resolves. The record has `approval_type="audit"` and is immediately in a final state (`status="approved"` or `status="rejected"`). Useful for audit trails without blocking on external approval systems.

`@approval(type="audit")` requires at least one HITL flag (`requires_confirmation`, `requires_user_input`, or `external_execution`) on the `@tool()` decorator.

## Examples

### `@approval` (Blocking Approvals)

| File | Description |
|------|-------------|
| `approval_basic.py` | Basic agent approval with SQLite - shows tool pause, DB record creation, and resolution |
| `approval_async.py` | Async variant of the basic approval flow |
| `approval_team.py` | Team-level approval - member agent tool triggers team pause with approval record |
| `approval_list_and_resolve.py` | Simulates the full API workflow: pause, list pending, resolve via DB, continue |
| `approval_user_input.py` | Approval with user input - `@approval` + `@tool(requires_user_input=True)` |
| `approval_external_execution.py` | Approval with external execution - `@approval` + `@tool(external_execution=True)` |

### `@approval(type="audit")` (Audit-Logged Approvals)

| File | Description |
|------|-------------|
| `audit_approval_confirmation.py` | Audit approval with confirmation - shows both approval and rejection paths |
| `audit_approval_user_input.py` | Audit approval with user input |
| `audit_approval_external.py` | Audit approval with external execution |
| `audit_approval_async.py` | Async variant of audit approval with confirmation |
| `audit_approval_overview.py` | Mixed overview - both `@approval` and `@approval(type="audit")` in one agent |

## Key Concepts

- `@approval` + `@tool(requires_confirmation=True)` - Creates a blocking approval record (`approval_type="required"`) before tool execution.
- `@approval(type="audit")` + `@tool(requires_confirmation=True)` - Logs the HITL resolution result (`approval_type="audit"`) after tool execution.
- Import: `from agno.approval import approval`
- Approval records are stored in the `agno_approvals` table (configurable via `approvals_table`).
- Each approval has a status: `pending`, `approved`, `rejected`, `expired`, `cancelled`.
- The `approval_type` field distinguishes `"required"` (blocking) from `"audit"` (audit) records.
- The `update_approval` method uses an `expected_status` guard for atomic resolution (prevents race conditions).
- You can filter approvals by type: `db.get_approvals(approval_type="required")` or `db.get_approvals(approval_type="audit")`.

## Running

```bash
.venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_basic.py
```
