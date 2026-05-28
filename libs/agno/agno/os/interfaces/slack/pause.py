from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from agno.os.interfaces.slack.builders import build_pause_message
from agno.os.interfaces.slack.helpers import slack_error_code
from agno.os.interfaces.slack.types import block_to_dict, tool_name
from agno.utils.log import log_error

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from agno.run.requirement import RunRequirement

_PAUSE_LABELS = {
    "confirmation": "⏸ *Awaiting approval of* `{tool}`…",
    "user_input": "⏸ *Awaiting input for* `{tool}`…",
    "user_feedback": "⏸ *Awaiting feedback*…",
    "external_execution": "⏸ *Awaiting output for* `{tool}`…",
}


async def finalize_pause(
    *,
    client: "AsyncWebClient",
    stream: Any,
    state: Any,
    run_id: str,
    channel: str,
    thread_ts: str,
    requirements: List["RunRequirement"],
    log_prefix: str = "",
) -> Optional[str]:
    # Build stop kwargs from accumulated state
    stop_kwargs = {}
    if state.has_content():
        stop_kwargs["markdown_text"] = state.flush()
    if state.task_cards:
        chunks = state.resolve_all_pending("pending")
        if chunks:
            stop_kwargs["chunks"] = chunks

    try:
        await stream.stop(**stop_kwargs)
    except Exception as exc:
        log_error(f"[HITL] stream.stop failed: run_id={run_id} err={slack_error_code(exc)!r} | {exc}")

    # Post "awaiting" indicator message
    labels = [_PAUSE_LABELS[r.pause_type].format(tool=tool_name(r)) for r in requirements]
    if not labels:
        return None

    try:
        resp = await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text="\n".join(labels))
        return resp.get("ts")
    except Exception as exc:
        log_error(f"[HITL] awaiting indicator failed: {exc}")
        return None


# Posts HITL card with approval buttons — separate message since chat_appendStream rejects Block Kit
async def post_pause_card(
    client: "AsyncWebClient",
    paused_event: Any,
    channel: str,
    thread_ts: str,
    awaiting_ts: Optional[str] = None,
) -> Optional[str]:
    run_id = getattr(paused_event, "run_id", None)
    requirements = list(getattr(paused_event, "active_requirements", None) or [])
    if not run_id or not requirements:
        return None

    try:
        blocks = build_pause_message(run_id, requirements, awaiting_ts)
        resp = await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Run paused — please resolve below",
            blocks=[block_to_dict(b) for b in blocks],
        )
        return resp.get("ts")
    except Exception as exc:
        log_error(f"[HITL] post_pause_card failed: run_id={run_id} | {exc}")
        return None
