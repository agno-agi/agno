from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.os.interfaces.slack.builders import build_pause_message
from agno.os.interfaces.slack.types import _tool_name
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
    stop_kwargs: Dict[str, Any] = {}
    if state.has_content():
        stop_kwargs["markdown_text"] = state.flush()
    if state.task_cards:
        pending_chunks = state.resolve_all_pending("pending")
        if pending_chunks:
            stop_kwargs["chunks"] = pending_chunks

    try:
        await stream.stop(**stop_kwargs)
    except Exception as exc:
        from agno.os.interfaces.slack.router import _slack_err_code

        log_error(
            f"[HITL] stream.stop on {log_prefix}pause failed: run_id={run_id} "
            f"slack_error={_slack_err_code(exc)!r} | {exc}"
        )

    awaiting_ts: Optional[str] = None
    # Build pause labels inline — maps pause_type to user-visible status text
    pause_labels = [_PAUSE_LABELS[r.pause_type].format(tool=_tool_name(r)) for r in requirements]
    if pause_labels:
        try:
            awaiting_resp = await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="\n".join(pause_labels),
                mrkdwn=True,
            )
            awaiting_ts = awaiting_resp.get("ts")
        except Exception as exc:
            log_error(f"[HITL] chat_postMessage (awaiting indicator, {log_prefix}pause) failed: {exc}")

    return awaiting_ts


async def post_pause_card(
    client: "AsyncWebClient",
    paused_event: Any,
    channel: str,
    thread_ts: str,
    awaiting_ts: Optional[str] = None,
) -> Optional[str]:
    # Separate message needed — chat_appendStream rejects Block Kit; mutated in-place by decision handler
    run_id = getattr(paused_event, "run_id", None)
    requirements = list(getattr(paused_event, "active_requirements", None) or [])
    if not run_id or not requirements:
        return None

    try:
        blocks = build_pause_message(run_id, requirements, awaiting_ts)

        def to_dict(b: Any) -> Dict[str, Any]:
            if hasattr(b, "to_dict"):
                return b.to_dict()
            if hasattr(b, "model_dump"):
                return b.model_dump(exclude_none=True, mode="json")
            if is_dataclass(b) and not isinstance(b, type):
                return asdict(b)
            raise TypeError(f"Cannot serialize block of type {type(b).__name__}")

        block_dicts = [to_dict(b) for b in blocks]
        resp = await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Run paused — please resolve below",
            blocks=block_dicts,
        )
        ts = resp.get("ts") if isinstance(resp, dict) else getattr(resp, "data", {}).get("ts")
        return str(ts) if ts else None
    except Exception as exc:
        log_error(f"Failed to post pause card (run_id={run_id}): {exc}")
        return None
