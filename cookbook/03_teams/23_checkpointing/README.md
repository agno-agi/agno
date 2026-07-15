# Team Checkpointing & Crash Recovery

Direct parity with the agent surface — same verbs, same flags, same
auto-fork-on-COMPLETED semantics. `Team(checkpoint="tool-batch")` writes the
team run after each team-level tool batch (a delegation to a member **is** a tool
batch), giving mid-run durability and crash recovery.

Members are out of scope of the team's checkpoint: from the team's perspective a
member is just a tool it delegated to (its output becomes a tool-role message in
the team's conversation). Fork / regenerate / time-travel operate on the team's
own state, not member state.

The three `/continue` capabilities live in sibling folders:

- [`../24_regenerate/`](../24_regenerate/) — redo the last response
- [`../25_time_travel/`](../25_time_travel/) — rewind (`continue_from`, `fork`)
- [`../26_fork_session/`](../26_fork_session/) — copy a whole session

## Examples

| Example | What it shows |
|---|---|
| [`01_crash_recovery.py`](./01_crash_recovery.py) | Cancel an in-flight team run to simulate a crash; the DB has the last checkpoint (status `RUNNING`) and `/continue` resumes it in place. |
| [`02_tool_error_persistence.py`](./02_tool_error_persistence.py) | A tool exception is caught and recorded; a model-call failure escapes the loop but the in-flight conversation is flushed onto the `ERROR` row, and `/continue` retries it. |
| [`03_checkpoint_endpoints.py`](./03_checkpoint_endpoints.py) | The two GET endpoints — `/checkpoints` (timeline) and `/checkpoints/{message_index}` (snapshot) — and feeding a returned index back into `/continue`. |

## Checkpoint policies (`Team(checkpoint=...)`)

- `"runs"` (default) — write only at terminal states. Same as agent default.
- `"tool-batch"` — write after each team-level tool batch. Enables crash recovery.
- `"tools"` — reserved for 3.0 (raises `NotImplementedError`).

## Running

```bash
.venvs/demo/bin/python cookbook/03_teams/23_checkpointing/01_crash_recovery.py
.venvs/demo/bin/python cookbook/03_teams/23_checkpointing/02_tool_error_persistence.py
.venvs/demo/bin/python cookbook/03_teams/23_checkpointing/03_checkpoint_endpoints.py
```
