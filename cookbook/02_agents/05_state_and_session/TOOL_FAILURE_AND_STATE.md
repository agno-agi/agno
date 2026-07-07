# Tool Failures, Session State, and Memory

When a tool fails during an agent run, persistence behavior depends on **what failed** and **when state was written**.

## Tool raises an exception (most common)

If a tool raises a regular Python exception (for example `ValueError`):

1. The model loop **catches** the error internally.
2. The failure is recorded as a tool-role message with `tool_call_error=True`.
3. The model can retry with a different approach or explain the error to the user.
4. The run typically **completes normally**; no conversation data is lost.

**Session state:** Changes made by tools that ran **before** the failing call are kept. If the failing tool was supposed to update `session_state`, that update does not happen.

**Memory:** `update_memory_on_run` and agentic memory run after a successful response. A completed run still extracts memories; a run that ends in `ERROR` may not.

See: `../18_checkpointing/02_tool_error_persistence.py` (Scenario A)

## Model call fails before tools run

If the model API call itself fails (auth error, rate limit, timeout):

1. The exception may **escape** the inner tool loop.
2. Per-batch checkpoint hooks may not have fired yet.
3. Without error flushing, the persisted run row can end up with **empty messages**.

Agno flushes in-flight messages on error so the conversation that led to the failure is preserved. Use checkpointing when you need crash-safe recovery.

See: `../18_checkpointing/02_tool_error_persistence.py` (Scenario B)

## Practical checklist

| Question | Guidance |
|---|---|
| Did my tool update `session_state` before failing? | Earlier updates persist; the failed tool's changes do not. |
| Will the user see the error? | Yes, as a tool error message in the chat transcript. |
| Should I use checkpointing? | Yes, for long multi-tool runs or HITL flows where recovery matters. |
| Does memory update on tool failure? | Only if the run completes and memory extraction runs successfully. |

## Related examples

| Topic | Location |
|---|---|
| Tool error vs model error | `../18_checkpointing/02_tool_error_persistence.py` |
| Session state basics | `session_state_basic.py` |
| HITL + session state survival | `../10_human_in_the_loop/confirmation_with_session_state.py` |