# 12_feedback

Examples for recording user feedback on agent runs and having the agent learn from it.

## Files

- `01_basic_feedback.py`: Record positive/negative with a comment on a run and see the agent adapt on the next run.
- `02_conversational_feedback.py`: No UI needed - feedback expressed in the chat ("too long, just the number") is extracted automatically after the run (ALWAYS mode).
- `03_agentic_feedback.py`: AGENTIC mode - the agent is given a `record_feedback` tool and logs feedback itself during the run.

## Modes

- **ALWAYS** (default): a background pass extracts feedback from the conversation after each run.
- **AGENTIC**: the agent logs feedback itself via a `record_feedback` tool during the run.
- **PROPOSE / HITL**: not supported (a warning is logged); use ALWAYS or AGENTIC.

Both capturing modes turn `add_history_to_context` on, even if you set it to `False`:
feedback reacts to the assistant's previous turn, and "too long" says nothing without
the response it refers to.

## AgentOS API

Run reviews can also be recorded over the AgentOS API. The routes are always available -- `LearningMachine(feedback=True)` is what makes an agent *read* the feedback back, not what makes the endpoints work:

- `POST /sessions/{session_id}/runs/{run_id}/feedback` with `{"signal": "negative", "comment": "..."}`
- `GET /sessions/{session_id}/runs/{run_id}/feedback`
- `DELETE /sessions/{session_id}/runs/{run_id}/feedback`

Feedback is keyed by run, so reviewing the same run again (e.g. toggling positive to
negative) updates the existing feedback instead of creating a duplicate.

The endpoints store the raw comment; model distillation of a lesson only happens when
recording through `feedback_store.record()`. The raw comment is injected into future
runs either way.
