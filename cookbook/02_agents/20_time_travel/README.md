# Time Travel

Rewind a run to an earlier point and resume from there. The boundary is chosen
with `continue_from`:

- `"end"` — keep the whole transcript (a normal follow-up)
- `"last_user"` — keep through the last user message, drop the post-user tail (tools re-invoke)
- `K` (int) — keep `messages[:K]`, an exact message-index boundary

For a `COMPLETED` run, `/continue` **auto-forks** into a new sibling run so the
"1 run = 1 model loop" contract holds — the source stays intact. Passing
`fork=True` makes that explicit and also works on non-completed runs: it creates
a sibling instead of resuming in place. So run-level fork is just time-travel
that **keeps both** the original and the new line, side by side in one session.

Boundaries are snapped to a tool-call-safe index automatically: a cut that would
orphan an assistant tool_call from its result is moved back to the start of that
exchange, so the resumed transcript is always valid.

| Example | What it shows |
|---|---|
| [`01_continue_from.py`](./01_continue_from.py) | `continue_from="end"`, `"last_user"`, and the numeric `K` form. COMPLETED runs auto-fork. |
| [`02_fork_run.py`](./02_fork_run.py) | `fork=True` + a boundary to create an explicit non-destructive sibling run — for evals / A-B exploration from a known state. |

```bash
.venvs/demo/bin/python cookbook/02_agents/20_time_travel/01_continue_from.py
.venvs/demo/bin/python cookbook/02_agents/20_time_travel/02_fork_run.py
```

## Related

- Redo just the last answer (keep tool exchanges): [`../19_regenerate/`](../19_regenerate/)
- Copy a whole session instead of one run: [`../21_fork_session/`](../21_fork_session/)
- The persistence layer this resumes from: [`../18_checkpointing/`](../18_checkpointing/)
