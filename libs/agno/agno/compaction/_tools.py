"""Model-facing compaction tools, registered when Compaction(expose_tools=True).

Payloads are ids and numbers, never summary text: what the model already has in context is its
own view; these tools exist for status awareness and for scheduling a pass ahead of big work.
"""

import json
from typing import Any, Optional

from agno.run import RunContext
from agno.tools.function import Function


def _state_for(run_context: RunContext):
    from agno.compaction._state import get_run_state

    return get_run_state(getattr(run_context, "run_id", None))


def get_compact_status_function(owner: Any, run_context: RunContext, async_mode: bool = False) -> Function:
    """Factory for the compact_status tool."""

    def _status() -> str:
        state = _state_for(run_context)
        if state is None:
            return "Error: compaction is not active for this run"
        tokens = state.gauge.last_reading or 0
        window = state.limits.window
        payload = {
            "tokens": tokens,
            "trigger_tokens": state.limits.trigger_tokens,
            "window": window,
            "percent_used": round(100.0 * tokens / window, 1) if window else None,
            "records": [
                {
                    "id": record.id,
                    "reason": record.reason,
                    "created_at": record.created_at,
                    "tokens_before": record.stats.get("tokens_before"),
                    "tokens_after": record.stats.get("tokens_after"),
                }
                for record in state.chain
            ],
        }
        return json.dumps(payload)

    def compact_status() -> str:
        """Current context usage and compaction history for this conversation.

        Returns:
            str: JSON with tokens, trigger_tokens, window, percent_used, and the list of past
                compaction records (ids and token counts).
        """
        return _status()

    async def acompact_status() -> str:
        """Current context usage and compaction history for this conversation.

        Returns:
            str: JSON with tokens, trigger_tokens, window, percent_used, and the list of past
                compaction records (ids and token counts).
        """
        return _status()

    function = Function.from_callable(acompact_status if async_mode else compact_status, name="compact_status")
    return function


def get_compact_run_function(owner: Any, run_context: RunContext, async_mode: bool = False) -> Function:
    """Factory for the compact_run tool."""

    def _schedule(instructions: Optional[str]) -> str:
        state = _state_for(run_context)
        if state is None:
            return "Error: compaction is not active for this run"
        if state.scheduled:
            return "A compaction pass is already scheduled for the next step."
        state.scheduled = True
        state.scheduled_instructions = instructions
        return "Compaction scheduled: older context will be folded into the summary before the next step."

    def compact_run(instructions: Optional[str] = None) -> str:
        """Compact this conversation before the next step: older messages fold into the running
        summary, freeing context for upcoming work. Use before starting something large.

        Args:
            instructions: Optional note on what the summary should keep in extra detail.

        Returns:
            str: Confirmation that the pass is scheduled.
        """
        return _schedule(instructions)

    async def acompact_run(instructions: Optional[str] = None) -> str:
        """Compact this conversation before the next step: older messages fold into the running
        summary, freeing context for upcoming work. Use before starting something large.

        Args:
            instructions: Optional note on what the summary should keep in extra detail.

        Returns:
            str: Confirmation that the pass is scheduled.
        """
        return _schedule(instructions)

    function = Function.from_callable(acompact_run if async_mode else compact_run, name="compact_run")
    return function
