# Team Time Travel

Rewind a team run to an earlier point and resume. The boundary is chosen with
`continue_from`:

- `"end"` — keep the whole transcript
- `"last_user"` — keep through the last user message, drop the post-user tail
- `K` (int) — keep `messages[:K]`

A `COMPLETED` team run **auto-forks** into a new sibling so the source remains a
durable record of the completed model loop. `fork=True` makes that explicit and
also works on non-completed runs — run-level fork is time-travel that keeps both
the original and the new line in the same session. Boundaries are snapped to a
tool-call-safe index so the resumed transcript is never left with an orphaned
delegation.

| Example | What it shows |
|---|---|
| [`01_continue_from.py`](./01_continue_from.py) | `continue_from="end"`, `"last_user"`, and the numeric `K` form. COMPLETED runs auto-fork. |
| [`02_fork_run.py`](./02_fork_run.py) | `fork=True` + `continue_from` for an explicit non-destructive sibling team run. |

```bash
.venvs/demo/bin/python cookbook/03_teams/25_time_travel/01_continue_from.py
.venvs/demo/bin/python cookbook/03_teams/25_time_travel/02_fork_run.py
```

## Related

- Redo just the last answer: [`../24_regenerate/`](../24_regenerate/)
- Copy a whole session: [`../26_fork_session/`](../26_fork_session/)
- The persistence layer: [`../23_checkpointing/`](../23_checkpointing/)
