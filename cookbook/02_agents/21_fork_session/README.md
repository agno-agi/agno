# Fork Session

`agent.fork_session()` deep-copies an entire session into a **new, independent
session** — every run is copied with a fresh `run_id`, under a fresh
`session_id`. The source session is untouched. Use it to branch a whole
conversation thread and explore a different direction without mutating the
original.

This is the session-level sibling of run-level `fork` (see
[`../20_time_travel/`](../20_time_travel/)):

| | `fork=True` | `fork_session()` |
|---|---|---|
| Granularity | **Run** | **Session** |
| Result | new sibling run, same session | new session with copies of every run |
| Endpoint | `POST /runs/{run_id}/continue` | `POST /sessions/{session_id}/fork` |
| Lineage field | `run.forked_from_run_id` | `run.forked_from_session_id` |

The verb is consistent across both: *fork = diverge a copy; the suffix tells you
what you're copying.*

| Example | What it shows |
|---|---|
| [`01_fork_session.py`](./01_fork_session.py) | `fork_session()` / `afork_session()` and the `forked_from_session_id` lineage across nested forks. |

```bash
.venvs/demo/bin/python cookbook/02_agents/21_fork_session/01_fork_session.py
```
