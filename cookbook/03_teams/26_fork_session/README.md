# Team Fork Session

`team.fork_session()` deep-copies an entire team session into a **new,
independent session** — every run is copied with a fresh `run_id`, under a fresh
`session_id`. The source is untouched. Use it to branch a whole team
conversation and explore a different direction.

Session-level sibling of run-level `fork` (see
[`../25_time_travel/`](../25_time_travel/)):

| | `fork=True` | `fork_session()` |
|---|---|---|
| Granularity | **Run** | **Session** |
| Result | new sibling run, same session | new session with copies of every run |
| Endpoint | `POST /runs/{run_id}/continue` | `POST /sessions/{session_id}/fork` |
| Lineage field | `run.forked_from_run_id` | `run.forked_from_session_id` |

| Example | What it shows |
|---|---|
| [`01_fork_session.py`](./01_fork_session.py) | `fork_session()` / `afork_session()` and the `forked_from_session_id` lineage across nested forks. |

```bash
.venvs/demo/bin/python cookbook/03_teams/26_fork_session/01_fork_session.py
```
