from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.os.interfaces.slack.builders import classify_requirement
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


def build_pause_labels(requirements: List["RunRequirement"]) -> List[str]:
    labels: List[str] = []
    for requirement in requirements:
        kind = classify_requirement(requirement)
        tool = _tool_name(requirement)
        labels.append(_PAUSE_LABELS[kind].format(tool=tool))
    return labels


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
    pause_labels = build_pause_labels(requirements)
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
