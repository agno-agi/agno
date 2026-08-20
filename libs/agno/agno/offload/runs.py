"""Offloading a stored member run.

A member's answer reaches the team leader as a tool result and is offloaded
there. The member's own run is stored separately, and it holds that answer
again, in full. That copy is what the member replays as its own history on its
next turn, so it is context as well as storage.

Only ``messages`` is replaced. ``content`` is what a caller reads back from
``RunOutput``, and offloading changes what a model reads, never what a caller
reads.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Optional

from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.offload.store import ResultStore

# The member's own instructions are small and the model needs them verbatim.
_NEVER_OFFLOADED_ROLES = ("system", "developer")


def offload_run_for_storage(
    store: "ResultStore",
    run: Any,
    *,
    session_id: str,
    user_id: Optional[str] = None,
) -> Any:
    """A storage copy of ``run`` whose oversized messages hold envelopes.

    Returns ``run`` itself when nothing qualifies, so the common path allocates
    nothing. The original is never modified: the live object is still handed
    back to the caller through ``RunOutput.member_responses``.

    A paused run is returned untouched. Resuming replays its messages verbatim
    into the model loop, so a pointer there would lose the conversation that
    produced the pending tool call.
    """
    if getattr(run, "is_paused", False):
        return run

    messages = getattr(run, "messages", None)
    if not messages:
        return run

    run_id = getattr(run, "run_id", None)
    if not run_id:
        return run

    replacements = {}
    for index, message in enumerate(messages):
        content = getattr(message, "content", None)
        role = getattr(message, "role", None)
        if role in _NEVER_OFFLOADED_ROLES or not isinstance(content, str):
            continue
        if not store.should_offload(getattr(message, "tool_name", None), content):
            continue
        try:
            envelope = store.offload_for_model(
                session_id=session_id,
                run_id=run_id,
                tool_call_id=f"message:{index}",
                tool_name=getattr(message, "tool_name", None) or f"{role}_message",
                tool_args={},
                output=content,
                user_id=user_id,
                shared=True,
            )
        except Exception as e:
            log_warning(f"Offloading a stored message of run {run_id} failed: {e}")
            continue
        replacements[index] = envelope

    if not replacements:
        return run

    storage_copy = copy.copy(run)
    storage_copy.messages = [
        message.model_copy(update={"content": replacements[index]}) if index in replacements else message
        for index, message in enumerate(messages)
    ]
    log_debug(f"Offloaded {len(replacements)} stored message(s) of run {run_id}")
    return storage_copy


__all__ = ["offload_run_for_storage"]
