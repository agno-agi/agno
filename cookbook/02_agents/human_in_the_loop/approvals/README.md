# Human Approvals

These cookbooks demonstrate the **@approval** decorator, which stacks on top of `@tool` to create persistent, queryable approval records in the database when a tool pauses an agent run.

## The @approval Decorator

`@approval` is applied **on top of** `@tool` (i.e., it wraps the `Function` object returned by `@tool`). It marks the tool so that when the agent pauses, an approval record is written to the database.

```python
from agno.tools import approval, tool

@approval
@tool(requires_confirmation=True)
def dangerous_action(target: str) -> str:
    ...
```

The decorator supports two modes:
- `@approval` (default `mode="required"`) -- approval must be resolved before the run continues.
- `@approval(mode="log")` -- approval record is created for audit trail only.

## Examples

| File | Description |
|------|-------------|
| `approval_basic.py` | Basic agent approval with SQLite using `@approval` + `@tool(requires_confirmation=True)` |
| `approval_async.py` | Async variant using `arun()` and `acontinue_run()` |
| `approval_team.py` | Team-level approval - member agent tool with `@approval` |
| `approval_list_and_resolve.py` | Full lifecycle: pause, list, filter, resolve, delete |
| `approval_user_input.py` | `@approval` + `@tool(requires_user_input=True)` - approval with user-provided input |
| `approval_log_mode.py` | `@approval(mode="log")` - audit-only mode |

## Key Concepts

- `@approval` must be applied **after** `@tool` (on top of `@tool`).
- The underlying `@tool` must have a HITL flag set: `requires_confirmation`, `requires_user_input`, or `external_execution`.
- Approval records capture `pause_type` ("confirmation", "user_input", "external_execution") so the UI renders the right interaction.
- Each approval has a status: `pending`, `approved`, `rejected`, `expired`, `cancelled`.
- The `update_approval` method uses an `expected_status` guard for atomic resolution (prevents race conditions).

## Running

```bash
.venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_basic.py
```
