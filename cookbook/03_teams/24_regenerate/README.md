# Team Regenerate

Redo the last response of a team run. `regenerate=True` drops only the trailing
assistant answer, keeps intermediate tool exchanges (member delegations are not
re-run), and re-generates a fresh final answer.

Regenerate **always forks** — a new team `run_id` with fresh metrics; the source
is always retained. `replace_original` controls only history visibility of the
source:

- default (`replace_original=True`) — source marked `REGENERATED` and hidden; new run replaces it
- `replace_original=False` — source stays `COMPLETED` and visible, so both attempts show

Member rows the original team produced stay attached to the original team — fork
replays the team's own model loop with a new `run_id`; delegated work that
already happened is a fact of history, not state to copy.

| Example | What it shows |
|---|---|
| [`01_regenerate.py`](./01_regenerate.py) | `team.continue_run(regenerate=True)` — new `run_id`, fresh metrics, original team and members untouched. |

```bash
.venvs/demo/bin/python cookbook/03_teams/24_regenerate/01_regenerate.py
```

Foundation: [`../23_checkpointing/`](../23_checkpointing/).
