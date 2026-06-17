# Regenerate

Redo the last response of a run. `regenerate=True` drops only the trailing
assistant answer, **keeps intermediate tool exchanges** (so tools are not
re-invoked), and re-runs the model to produce a fresh final answer.

Regenerate **always forks** — it creates a new run with a fresh `run_id`; the
source run is always retained in storage. `replace_original` controls only
whether the source stays *visible* in history:

- default (`replace_original=True`) — source marked `REGENERATED` and hidden; the new run replaces it
- `replace_original=False` — source stays `COMPLETED` and visible, so both attempts show in history for comparison

`replace_original` only decides whether *this* regenerate hides its source; it
never un-hides a run an earlier regenerate already replaced — so
`replace_original=False` is only meaningful on a still-`COMPLETED` source.
Regenerate the *latest* run, not an already-replaced one.

This is the foundation `checkpoint` feature in action via `/continue` — see
[`../18_checkpointing/`](../18_checkpointing/).

| Example | What it shows |
|---|---|
| [`01_regenerate.py`](./01_regenerate.py) | A replace chain (default) and a keep-both demo (`replace_original=False`), plus steering with `additional_instructions`. |

```bash
.venvs/demo/bin/python cookbook/02_agents/19_regenerate/01_regenerate.py
```

## Regenerate vs `continue_from="last_user"`

Both rewind, but they cut differently when tools are involved:

| Form | Keeps | Drops | Tools re-invoked? |
|---|---|---|---|
| `regenerate=True` | everything through the last tool exchange | only the trailing no-tool-call assistant turn | No |
| `continue_from="last_user"` | through the last user message | the whole post-user tail (tool_calls, results, reply) | Yes |

Use regenerate for "redo the final summary, same tool results." Use
`continue_from="last_user"` (see [`../20_time_travel/`](../20_time_travel/)) to
replay the whole turn from where the user spoke.
