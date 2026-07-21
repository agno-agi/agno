# 11_feedback

Examples for recording user feedback on agent runs and having the agent learn from it.

## Files

- `01_basic_feedback.py`: Record thumbs up/down with a comment on a run and see the agent adapt on the next run.
- `02_conversational_feedback.py`: No UI needed - feedback expressed in the chat ("too long, just the number") is extracted automatically after the run.

## AgentOS API

With feedback learning enabled, run reviews can also be recorded over the AgentOS API:

- `POST /sessions/{session_id}/runs/{run_id}/feedback` with `{"signal": "thumbs_down", "comment": "..."}`
- `GET /sessions/{session_id}/runs/{run_id}/feedback`
- `DELETE /sessions/{session_id}/runs/{run_id}/feedback`

Feedback is keyed by run, so reviewing the same run again (e.g. toggling thumbs up to
thumbs down) updates the existing feedback instead of creating a duplicate.

The endpoints store the raw comment; model distillation of a lesson only happens when
recording through `feedback_store.record()`. The raw comment is injected into future
runs either way.
