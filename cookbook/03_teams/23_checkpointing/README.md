# Team Checkpointing

Team checkpointing is direct parity with the agent surface — same verbs,
same flags, same auto-fork-on-COMPLETED semantics. Members are out of
scope: from the team's perspective a member is just a tool the team
delegated to (its output becomes a tool-role message in the team's
conversation). Fork / regenerate / time-travel operates on the team's own
state, not member state.

| Example | What it shows |
|---|---|
| [`01_regenerate.py`](./01_regenerate.py) | `team.continue_run(regenerate=True)` drops the last assistant turn and replays. New `run_id`, fresh metrics. Original team and original members untouched. |
| [`02_fork.py`](./02_fork.py) | `fork=True, from_checkpoint=K` to fork at a specific message index. |
| [`03_time_travel.py`](./03_time_travel.py) | `from_checkpoint=K` alone (no `fork`) is destructive — same run_id, rewound in place. |
| [`04_crash_recovery.py`](./04_crash_recovery.py) | `Team(checkpoint="steps")` writes a snapshot after every team-level tool batch. Crash mid-flight → fresh team `/continue`s the same `run_id`. |
| [`05_branch_session.py`](./05_branch_session.py) | `team.branch_session()` deep-copies every run into a new session. Independent conversation threads. |

## The unified `/continue` (same as agent)

| Body | Behavior |
|---|---|
| `tools=[...]` / `requirements=[...]` (PAUSED + HITL) | Apply tool results, resume |
| empty + COMPLETED | **Auto-fork**: new `run_id`, source preserved |
| empty + RUNNING / ERROR | Resume in place (loop didn't finish; retry semantics) |
| `regenerate=True` | Always forks: drop last assistant turn, fresh `run_id` |
| `regenerate=True, additional_instructions=...` | Same with steering text appended |
| `regenerate=True, preserve_original=True` | Source marked `REGENERATED` so history-builders skip it |
| `fork=True, from_checkpoint=K` | Fork at message index K |
| `from_checkpoint=K` (no fork) | Destructive rewind — same `run_id` |

## Why members aren't cloned on team fork

A team's `member_responses` is the team's record of who it delegated to.
The member RunOutput rows in `session.runs` (with `parent_run_id =
team.run_id`) are durable records of work that already happened.

Forking the team creates a new team run. From the new team's perspective:
- The original conversation context (including member outputs baked into
  messages) is the seed state.
- If the new team needs to delegate, it'll create new member runs naturally.
- The original member rows stay attached to the original team — they
  remain a durable record of that team's delegation.

This matches how agents handle "tool execution rows": fork doesn't clone
them. Fork is about replaying the team's own model loop with a new run_id;
delegated work that already happened is a fact of history, not state to
copy.

## Checkpoint policies (`Team(checkpoint=...)`)

- `"runs"` (default) — write only at terminal states. Same as agent default.
- `"steps"` — write after each team-level tool batch. Enables crash recovery.
- `"tools"` — reserved for 3.0 (raises `NotImplementedError`).

## Running the cookbooks

```bash
.venvs/demo/bin/python cookbook/03_teams/23_checkpointing/01_regenerate.py
.venvs/demo/bin/python cookbook/03_teams/23_checkpointing/02_fork.py
.venvs/demo/bin/python cookbook/03_teams/23_checkpointing/03_time_travel.py
.venvs/demo/bin/python cookbook/03_teams/23_checkpointing/04_crash_recovery.py
.venvs/demo/bin/python cookbook/03_teams/23_checkpointing/05_branch_session.py
```
