# Human Approvals

These cookbooks demonstrate the **requires_approval** feature, which builds on top of `requires_confirmation` to create persistent, queryable approval records in the database.

When a tool decorated with `@tool(requires_approval=True)` is called, the agent pauses and an approval record is written to the database. External systems (UIs, APIs, scripts) can then list, inspect, and resolve those approvals.

## Examples

| File | Description |
|------|-------------|
| `approval_basic.py` | Basic agent approval with SQLite - shows tool pause, DB record creation, and resolution |
| `approval_async.py` | Async variant of the basic approval flow |
| `approval_team.py` | Team-level approval - member agent tool triggers team pause with approval record |
| `approval_list_and_resolve.py` | Simulates the full API workflow: pause, list pending, resolve via DB, continue |

## Key Concepts

- `@tool(requires_approval=True)` - Semantic alias that sets `requires_confirmation=True` and marks the tool for approval record creation.
- Approval records are stored in the `agno_approvals` table (configurable via `approvals_table`).
- Each approval has a status: `pending`, `approved`, `rejected`, `expired`, `cancelled`.
- The `update_approval` method uses an `expected_status` guard for atomic resolution (prevents race conditions).

## Running

```bash
.venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_basic.py
```
